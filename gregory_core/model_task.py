"""One isolated model job. It receives data, never a Core/database handle."""
import queue
import threading
import time


class ModelTask:
    def __init__(self, provider, profile, prompt, seconds, images=None, screen_source=None, screen_session=None, absolute_deadline=None, screen_game_tasks=False, response_schema=None):
        self.started=time.monotonic()
        self.deadline=min(self.started+seconds,absolute_deadline) if absolute_deadline is not None else self.started+seconds
        self.output=queue.Queue(maxsize=1)
        self.terminal=False
        output=self.output
        self.screen_receipts=[]
        receipts=self.screen_receipts
        deadline=self.deadline
        def run():
            try:
                if screen_source is not None:
                    from gregory_core.screen import generate_with_screen
                    result=generate_with_screen(provider,profile,prompt,screen_source,screen_session,deadline,receipts,allow_game_task=screen_game_tasks,response_schema=response_schema)
                else:
                    from gregory_core.decision_contract import generate
                    result=generate(provider,profile,prompt,images=images,response_schema=response_schema)
                value=(True,result)
            except BaseException as exc:
                value=(False,exc if isinstance(exc,Exception) else RuntimeError(type(exc).__name__))
            output.put(value)
        # Hung transport cannot pin interpreter exit or access closed stores.
        self.thread=threading.Thread(target=run,name='gregory-model',daemon=True)
        self.thread.start()
