"""Process-boundary tests: launch engine hidden, reuse listeners, clean owned failures."""
from pathlib import Path
import sys,tempfile,unittest
from unittest.mock import Mock,MagicMock,patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'deployments/oldpc'))
import greg_sapi4 as sapi

class EngineLaunchTests(unittest.TestCase):
 def setUp(self):
  tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
  self.exe=Path(tmp.name)/'sapi4.exe';self.exe.write_bytes(b'fixture-not-executable')
  self.platform=patch.object(sapi.sys,'platform','win32');self.platform.start();self.addCleanup(self.platform.stop)
  self.flag=patch.object(sapi.subprocess,'CREATE_NO_WINDOW',0x08000000,create=True);self.flag.start();self.addCleanup(self.flag.stop)
 def test_actual_spawn_uses_no_window_and_no_shell(self):
  process=Mock();process.poll.return_value=None
  with patch.object(sapi.socket,'create_connection',side_effect=[OSError(),MagicMock()]),patch.object(sapi.subprocess,'Popen',return_value=process) as launch:
   self.assertIs(sapi.start_engine(self.exe),process)
  self.assertEqual(launch.call_args.args,([str(self.exe.resolve())],))
  self.assertEqual(launch.call_args.kwargs['creationflags'],0x08000000)
  self.assertNotIn('shell',launch.call_args.kwargs);process.terminate.assert_not_called()
 def test_existing_service_is_not_owned_or_restarted(self):
  with patch.object(sapi.socket,'create_connection',return_value=MagicMock()),patch.object(sapi.subprocess,'Popen') as launch:
   self.assertIsNone(sapi.start_engine(self.exe));launch.assert_not_called()
 def test_failed_startup_terminates_only_owned_process(self):
  process=Mock();process.poll.return_value=None
  with patch.object(sapi.socket,'create_connection',side_effect=OSError()),patch.object(sapi.subprocess,'Popen',return_value=process),patch.object(sapi.time,'monotonic',side_effect=[0,10]):
   with self.assertRaises(TimeoutError):sapi.start_engine(self.exe,timeout=1)
  process.terminate.assert_called_once();process.wait.assert_called_once_with(timeout=2)
 def test_early_exit_is_not_relabelled_as_ready(self):
  process=Mock();process.poll.return_value=1
  with patch.object(sapi.socket,'create_connection',side_effect=OSError()),patch.object(sapi.subprocess,'Popen',return_value=process):
   with self.assertRaisesRegex(RuntimeError,'exited'):sapi.start_engine(self.exe)
  process.terminate.assert_not_called()
 def test_arbitrary_program_or_unbounded_timeout_cannot_launch(self):
  other=self.exe.with_name('cmd.exe');other.write_bytes(b'fixture')
  with patch.object(sapi.subprocess,'Popen') as launch:
   with self.assertRaises(ValueError):sapi.start_engine(other)
   with self.assertRaises(ValueError):sapi.start_engine(self.exe,timeout=100)
   launch.assert_not_called()

if __name__=='__main__':unittest.main()
