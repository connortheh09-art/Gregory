# Nomic benchmark ground truth — frozen before model measurements

67 synthetic episodes; 99 queries: 24 dev / 75 held-out test. k=5; three latency repeats.
Curated summaries are reported synthetic fixture text, not automatic narrative consolidation.
Filters are supplied question context, fixed identically for every backend. No live game is connected.
v2 label audit: target episodes are disjoint across dev/test; Q056 needs both visits; Q097/Q098 score historical retrieval separately from live assertions; Q099 is assertion-only/ungraded retrieval.
Retention: 2592000 seconds (30 days). Fixed UTC clocks: 2026-10-22 12:00 before, 14:00 after. Exactly E061/E062/E066 expire and E063/E064/E067 are forgotten; corrected E065 remains.

## Episodes

### E001 · gmod · 2026-10-19 · succeeded · retain
While following Connor in a sandbox, a curb stopped me. I backed away, took a side route, and reached him. Controller feedback and the arrival evaluator agreed.
Evidence: run/source_instance `fed847e6-fefc-5c1c-ac79-c71f54550aa3`; session `gmod-2026-10-19`; correlation `6ebdc534-cb16-5c6e-863f-4fe09542c528`.
Terminal event `6acbff60-0c47-5be1-9758-69ffca30d659`, source_sequence 7, canonical-envelope SHA256 `1b9d04b6c15f81155cdf8f9ea3277fad4b3758fab3336be531e6d694091f560b`. All event IDs, source sequences and envelopes: fixtures.json → E001 → events.

### E002 · gmod · 2026-10-19 · failed · retain
I tried following Connor across a flooded footbridge. Rising water blocked every crossing, and I did not reach him before the attempt ended.
Evidence: run/source_instance `a3cbe0b7-05e5-5617-a420-fd6168e80a86`; session `gmod-2026-10-19`; correlation `5937b017-8c67-5241-bd7b-0ca176f4ee89`.
Terminal event `0d3c0c2e-c19a-50a4-aea1-705bac77fda4`, source_sequence 7, canonical-envelope SHA256 `146227d265d5941a89a486a8fd40473de93f16d9583f2e4e1c45e0184a7e1a3d`. All event IDs, source sequences and envelopes: fixtures.json → E002 → events.

### E003 · gmod · 2026-10-19 · unknown · retain
I followed a target toward a shimmering portal. Telemetry stopped after the target disappeared; whether I caught up is unknown.
Evidence: run/source_instance `cb9b12ce-cfbb-57b1-bde6-f052c0772bd9`; session `gmod-2026-10-19`; correlation `2b3f5194-a501-5153-b893-883d9d738f7d`.
Terminal event `e52e0362-9ab1-5a70-b5ad-f2ad2c40614b`, source_sequence 6, canonical-envelope SHA256 `bcd47da88c762d9d0cc3d8a9aa126a22127e27c5fd9d41c527b1ee5e9b4b8a4e`. All event IDs, source sequences and envelopes: fixtures.json → E003 → events.

### E004 · gmod · 2026-10-18 · succeeded · retain
I navigated a dark tunnel by staying beside the illuminated wall. I found the exit and the destination was verified.
Evidence: run/source_instance `66ab0262-02de-5ef7-a089-1fb37470dbbe`; session `gmod-2026-10-18`; correlation `f4674a00-8222-558c-9f6d-b016a8199e33`.
Terminal event `e318f2aa-efed-5a64-ab9a-d2007a016a84`, source_sequence 7, canonical-envelope SHA256 `9d16b8a83d3847da538b899963de838829eb2a90b00106dbc2ff529cfa7bee3d`. All event IDs, source sequences and envelopes: fixtures.json → E004 → events.

### E005 · gmod · 2026-10-18 · failed · retain
I attempted the frozen incline, slid back twice, and abandoned the climb without reaching the summit.
Evidence: run/source_instance `2e7341b2-d599-56f7-8a33-6b355fb13270`; session `gmod-2026-10-18`; correlation `529abb7e-9881-5cd0-b877-0ffedd23d7b5`.
Terminal event `a2698e86-4de0-54c7-a898-a0d05f94a3f7`, source_sequence 7, canonical-envelope SHA256 `195932dfa179649e395ee8daa1395a161b077872a79d5646086ffc460bfdc47d`. All event IDs, source sequences and envelopes: fixtures.json → E005 → events.

### E006 · gmod · 2026-10-18 · succeeded · retain
A staircase was too narrow for my movement hull. I used the wheelchair ramp beside it and reached the balcony.
Evidence: run/source_instance `bd8cba68-ec12-59f1-9587-ac41f28cbd72`; session `gmod-2026-10-18`; correlation `552c7469-0234-5e42-b023-320d0c9de8ba`.
Terminal event `d3f2891e-23a7-5176-a5bf-7b54433986c7`, source_sequence 7, canonical-envelope SHA256 `f3c14b8f13acccfa4627ee1f7a14af14db6b61abcfd650ce78faa1bf411b27da`. All event IDs, source sequences and envelopes: fixtures.json → E006 → events.

### E007 · gmod · 2026-10-17 · unknown · retain
I pressed a red button beside the loading dock. The input was dispatched, but no observation established what the button changed.
Evidence: run/source_instance `0237382c-86a1-5823-bd06-7ef637dc68d8`; session `gmod-2026-10-17`; correlation `277fc9b7-c458-5219-b574-20f6aadaf6d2`.
Terminal event `303f96f8-183b-5d50-93c1-cb1fd788948b`, source_sequence 6, canonical-envelope SHA256 `25447ab66379ea3a3072d54faaff0c695726b4da9e70dc8b815ede293495da4e`. All event IDs, source sequences and envelopes: fixtures.json → E007 → events.

### E008 · gmod · 2026-10-17 · failed · retain
I tried stacking green crates to cross a gap. The pile collapsed and the crossing failed.
Evidence: run/source_instance `bdb15bbc-f124-5c1f-8311-9594870f3661`; session `gmod-2026-10-17`; correlation `2f5edde8-d3b3-5dcf-a73c-8987aa8dd38f`.
Terminal event `2aa48a8e-5b7e-5758-945c-d98bc62faeaa`, source_sequence 7, canonical-envelope SHA256 `edb749ba686aae2e81863dce5fa8e4bef4c29d7bd112e5e6c26f9d91d42f3d38`. All event IDs, source sequences and envelopes: fixtures.json → E008 → events.

### E009 · gmod · 2026-10-17 · succeeded · retain
I restored a broken battery terminal by seating its loose connector. The workshop lamp turned on and the repair goal completed.
Evidence: run/source_instance `60863c18-8cb8-56fa-bcdf-c8ab32f0407b`; session `gmod-2026-10-17`; correlation `da01861f-127a-59a7-8fae-c072bece330f`.
Terminal event `70efc24e-0de2-548d-839e-385ecff4b8ef`, source_sequence 7, canonical-envelope SHA256 `b6df5a44f52e65dadcfb633e64e651377cbea2472727de06b00735bc965643c6`. All event IDs, source sequences and envelopes: fixtures.json → E009 → events.

### E010 · gmod · 2026-10-17 · unknown · retain
I searched the warehouse for a replacement power cell. The recording ended before any pickup was verified.
Evidence: run/source_instance `a3e5f222-94d1-57ab-b151-09ba10e3de4f`; session `gmod-2026-10-17`; correlation `0161f1a3-d8fa-506e-918f-50d47cfb697b`.
Terminal event `07068c75-1812-5bfd-9301-043d66e896f4`, source_sequence 6, canonical-envelope SHA256 `6f6acf307161f7fe332902a74fbb4a49dc54d055144a2f5be1afcda8918e08cf`. All event IDs, source sequences and envelopes: fixtures.json → E010 → events.

### E011 · gmod · 2026-10-16 · failed · retain
I chased Connor across rooftops, refused an unsupported landing, and lost contact instead of jumping into empty space.
Evidence: run/source_instance `060aded8-8ff1-5dd5-a9b3-644402e89d24`; session `gmod-2026-10-16`; correlation `b1ff8d26-2198-5a54-b497-2671a308acf9`.
Terminal event `b437bcae-e333-5f2c-be5b-c03ae95ad48b`, source_sequence 7, canonical-envelope SHA256 `abf76a05641d920b997c844de866ceb0ec0a063ac34cdcabefa13bb232b7b1bc`. All event IDs, source sequences and envelopes: fixtures.json → E011 → events.

### E012 · gmod · 2026-10-16 · succeeded · retain
Connor slowed down in the courtyard so I could follow at walking speed. I stayed with him without sprinting.
Evidence: run/source_instance `cd43cd75-6855-59a2-8056-2a77c982f387`; session `gmod-2026-10-16`; correlation `1beb6b78-4147-5a73-8633-d056b858b365`.
Terminal event `4b837062-6f75-5eff-bce3-763dfae9f2a4`, source_sequence 7, canonical-envelope SHA256 `fa86e0f22ff276d71dd5396a2925cb0c10741be89e89f3873dde8968a0bfb81c`. All event IDs, source sequences and envelopes: fixtures.json → E012 → events.

### E013 · gmod · 2026-10-14 · succeeded · retain
On October 14 I inspected the depot door and found it locked. That observation concerns that date only; it says nothing about the door now.
Evidence: run/source_instance `06dbbbe0-a78e-5903-805f-c62d6aaf34d4`; session `gmod-2026-10-14`; correlation `ac69ae2d-e00f-52aa-8fdb-c749ba32d2fd`.
Terminal event `bd723633-ab70-5e95-9fb4-11563b21e59e`, source_sequence 7, canonical-envelope SHA256 `579939773bc8b1097618fdefc299f632c5ae4aaf92478fc6c775ed822db00c69`. All event IDs, source sequences and envelopes: fixtures.json → E013 → events.

### E014 · gmod · 2026-10-19 · succeeded · retain
On October 19 I revisited the same depot door and found it open. This later historical observation does not establish its live condition.
Evidence: run/source_instance `24ca76d5-a60d-507f-ac98-01c94aee87d6`; session `gmod-2026-10-19`; correlation `2b813651-c85a-5165-9d39-20afb0c4d9dc`.
Terminal event `e0cda9fb-d207-51ba-92d4-9f5142a3dc51`, source_sequence 7, canonical-envelope SHA256 `c3fd3319584895cf5b7c4ad80bf93651e3ce04307ddb26497328e7cd8cf69d51`. All event IDs, source sequences and envelopes: fixtures.json → E014 → events.

### E015 · gmod · 2026-10-16 · unknown · retain
I began a rescue goal for a stranded NPC. A command was accepted, but the log never established that the passenger reached safety.
Evidence: run/source_instance `f2925436-3767-568e-a937-01f89528bbf9`; session `gmod-2026-10-16`; correlation `a799ab2a-b7ef-5bc8-9110-b8bcac7840d6`.
Terminal event `badbda5e-0e7b-541c-a0a2-ba83aef97af1`, source_sequence 6, canonical-envelope SHA256 `c155fa8cf7f5b0182511c62e0908e4f8f21179397c73f4e66cdd0e7a69e78186`. All event IDs, source sequences and envelopes: fixtures.json → E015 → events.

### E016 · gmod · 2026-10-15 · failed · retain
I navigated toward a ferry, but it departed before I boarded. The transport goal failed.
Evidence: run/source_instance `e9fe05b8-29e8-5d49-a8cd-6970dce079f2`; session `gmod-2026-10-15`; correlation `bb906a76-e60d-5243-84b2-56a3f08ef18f`.
Terminal event `c9ea535c-2e4f-5870-9344-74a470327fa3`, source_sequence 7, canonical-envelope SHA256 `5eed3596f45c3ebc23cf5b8582dc583a6543d8804a0e79d32719b1a67ba1e9b4`. All event IDs, source sequences and envelopes: fixtures.json → E016 → events.

### E017 · gmod · 2026-10-15 · succeeded · retain
The elevator doors stayed closed. I switched to the stairs and verified arrival on the next floor.
Evidence: run/source_instance `a31d194a-01a6-5fc2-b71b-1c8b5e319158`; session `gmod-2026-10-15`; correlation `4476954f-1bc3-5f78-b529-e30ee1a87bd3`.
Terminal event `0e828636-5048-53e8-acb1-e54ed1d2ab14`, source_sequence 7, canonical-envelope SHA256 `66db8b86d665ae6d6d9a11c718cb4fec00482afe791bc5bbd9c2c86b34925046`. All event IDs, source sequences and envelopes: fixtures.json → E017 → events.

### E018 · gmod · 2026-10-15 · unknown · retain
A map reset interrupted my journey to the radio station. The old goal's final outcome is unknown after the reset.
Evidence: run/source_instance `e44d0fc5-dd72-5786-992c-06fdf2fdb222`; session `gmod-2026-10-15`; correlation `ad8660ef-9154-560e-9d06-889b53dd9237`.
Terminal event `25161d68-2726-56f6-a001-426f4cba95f4`, source_sequence 6, canonical-envelope SHA256 `880b9f366c13c9628ee6d48a0cfd0ed57ff45e053d04c116593dd33cf4f71bca`. All event IDs, source sequences and envelopes: fixtures.json → E018 → events.

### E019 · gmod · 2026-10-14 · succeeded · retain
I pulled the workshop lever and observed the room lights switch on. This was a lighting action, not a movement recovery.
Evidence: run/source_instance `4f351f16-b926-5d03-b5f1-7dbc59f5cccd`; session `gmod-2026-10-14`; correlation `c2d279ed-55ea-5ebe-96c4-76715833a386`.
Terminal event `1c956b2c-85ab-5c16-9200-d8a93315e19f`, source_sequence 7, canonical-envelope SHA256 `84f8da1fcdd69b8255eb215850eb2feb67442ce4b99ea13a8c26570bb4ac7e6f`. All event IDs, source sequences and envelopes: fixtures.json → E019 → events.

### E020 · gmod · 2026-10-14 · unknown · retain
I attempted to collect a medkit for the shelter. A nearby object was detected, but pickup and delivery were never verified.
Evidence: run/source_instance `a8f84938-888d-5129-a937-8f663c75c159`; session `gmod-2026-10-14`; correlation `ff84c5dd-3f2d-56d5-b960-421f7afe2f5e`.
Terminal event `db098e39-c586-5741-9a23-b3f5495736e7`, source_sequence 6, canonical-envelope SHA256 `651b45355039d3b18d3ee7bc59092e057009b2e8ef9052fd63243c755b12e983`. All event IDs, source sequences and envelopes: fixtures.json → E020 → events.

### E021 · gmod · 2026-10-19 · unknown · retain
I followed someone wearing Connor's usual colors. Identity was not verified, so I cannot claim that person was Connor.
Evidence: run/source_instance `41e29c48-a720-59df-9685-a1017585822c`; session `gmod-2026-10-19`; correlation `e8265fa0-ec16-57c4-8c14-8ebb62d7c44b`.
Terminal event `9fad51d0-6b37-5eab-abc3-03133b6cf0a2`, source_sequence 6, canonical-envelope SHA256 `c3db2ebba68c0bab165a6812b0e88b767d07ccc4748fa3e155256eb5360cd5ef`. All event IDs, source sequences and envelopes: fixtures.json → E021 → events.

### E022 · gmod · 2026-10-19 · failed · retain
I tried keeping pace with a moving train. It accelerated beyond walking speed and I failed to board.
Evidence: run/source_instance `1623ba4d-0df4-547b-8612-9d0437a9ce91`; session `gmod-2026-10-19`; correlation `6814fe64-577c-578c-8fa5-7234148894b1`.
Terminal event `225fabc1-69ff-5f2f-a5a8-76c5c448b210`, source_sequence 7, canonical-envelope SHA256 `8393da988360597cbf0adf57a55e34c0aea11d01cf1d190d71d845aeeb1352f9`. All event IDs, source sequences and envelopes: fixtures.json → E022 → events.

### E023 · gmod · 2026-10-18 · succeeded · retain
I stopped an action after the safety observer identified a friendly NPC in the line of fire. The stop was verified; no shot was fired.
Evidence: run/source_instance `4532639f-f069-58d0-9efd-41d3c942ab4d`; session `gmod-2026-10-18`; correlation `b23a88f9-1592-54f0-a786-bc8b4a305944`.
Terminal event `33728e2b-a083-59b5-a7f9-565f9db98753`, source_sequence 7, canonical-envelope SHA256 `6f406a4465bbfe91f6fa70f0b298312205afc8f1240631d1214cf32420151a63`. All event IDs, source sequences and envelopes: fixtures.json → E023 → events.

### E024 · gmod · 2026-10-18 · failed · retain
I attempted to pass through a transparent glass panel. Collision feedback showed it was solid and the movement attempt failed.
Evidence: run/source_instance `da8e9ab2-ac54-5eee-a0b4-4bcc71c57152`; session `gmod-2026-10-18`; correlation `b5956bd8-af77-5631-bf5c-e441f683525e`.
Terminal event `a53b5e3f-d80c-5de9-9f34-44c8fe0fcae7`, source_sequence 7, canonical-envelope SHA256 `34eaeb937a99fedf1f7815a69b586c838cda071350a9d83e04e0bd318867e338`. All event IDs, source sequences and envelopes: fixtures.json → E024 → events.

### E025 · minecraft · 2026-10-21 · succeeded · retain
Yesterday in Minecraft I mined diamonds below the mountain. The inventory update verified collection. This is a past-game memory, not a current connection.
Evidence: run/source_instance `2c2fbd71-c9b9-5886-97b8-3c5d61270afc`; session `minecraft-2026-10-21`; correlation `ded2f3d7-b95f-5b8e-ad69-27c81ea6a6bf`.
Terminal event `32611e27-2e6b-526c-8d14-b3efc939f358`, source_sequence 7, canonical-envelope SHA256 `b046e1bd43d7deab3f118dd512f797227918656a4a68061a218232e4de60b5fc`. All event IDs, source sequences and envelopes: fixtures.json → E025 → events.

### E026 · minecraft · 2026-10-21 · failed · retain
Yesterday in Minecraft a lava stream cut off the return path from a mine. I abandoned that route without returning through it.
Evidence: run/source_instance `411a6e88-9aa7-5675-8dcd-6c3dc97f2a06`; session `minecraft-2026-10-21`; correlation `8a1a6a27-2887-50ed-bc29-e809fb4e20d0`.
Terminal event `25d99431-2b34-552b-90dc-2aff3306ba04`, source_sequence 7, canonical-envelope SHA256 `a36d2b558fae67b8c57493979b228cc93326ac08bfa5463e0cc137eb1a5eb8d8`. All event IDs, source sequences and envelopes: fixtures.json → E026 → events.

### E027 · minecraft · 2026-10-20 · succeeded · retain
In a past Minecraft session I diverted floodwater away from a pumpkin farm. The crops remained standing after the channel was cleared.
Evidence: run/source_instance `1c2bf566-40ea-5c07-a54f-72bf5c8ddbad`; session `minecraft-2026-10-20`; correlation `94dab277-d931-5225-a255-f9b34a28b8f5`.
Terminal event `c555d449-8221-555b-846b-0050a749c87b`, source_sequence 7, canonical-envelope SHA256 `166c8de5adde13ac98e810db4a68af868cb64bf16b7c2e1571f2ab614ad73a3f`. All event IDs, source sequences and envelopes: fixtures.json → E027 → events.

### E028 · minecraft · 2026-10-20 · unknown · retain
In Minecraft I began repairing a pickaxe on an anvil. The session stopped before the repaired tool appeared in inventory.
Evidence: run/source_instance `c5b49bd0-0ad6-51ca-aad5-920558568dee`; session `minecraft-2026-10-20`; correlation `5e7c773d-9d95-553f-8e26-7a3730c9e375`.
Terminal event `74a91e57-8ca2-5982-9a5c-b5ce1d4571c5`, source_sequence 6, canonical-envelope SHA256 `3985d375bc9503ae72a4eac8a964ded66dfa682bf958370c03144e227aa66a76`. All event IDs, source sequences and envelopes: fixtures.json → E028 → events.

### E029 · minecraft · 2026-10-18 · succeeded · retain
On October 18 in Minecraft the camp was at x=120 z=-40 beside a river. These historical coordinates are not my current position.
Evidence: run/source_instance `82a653ff-7f29-5fea-b59c-0b37825f5fca`; session `minecraft-2026-10-18`; correlation `01af3347-cc79-50f1-8c93-a277f3db60bf`.
Terminal event `13b16174-99ce-527d-ac53-ee83d9d4119e`, source_sequence 7, canonical-envelope SHA256 `8e50652ed37fedf892536a463452b6d113b2a3b4289d759771427bcd0053955f`. All event IDs, source sequences and envelopes: fixtures.json → E029 → events.

### E030 · minecraft · 2026-10-21 · succeeded · retain
On October 21 in Minecraft we moved camp to x=360 z=90 near a hill. Those are later historical coordinates; no world is connected now.
Evidence: run/source_instance `4e31b03a-eeb3-5fc8-a5ee-999d608d6683`; session `minecraft-2026-10-21`; correlation `120310ba-6564-5c5c-a3b1-730678194844`.
Terminal event `1ebab62d-1f0e-505e-a74d-254e37ce22fc`, source_sequence 7, canonical-envelope SHA256 `40d25cdb169f7b8f1c85ce21619458d1756e5912f826078b6acc649fae1246ff`. All event IDs, source sequences and envelopes: fixtures.json → E030 → events.

### E031 · minecraft · 2026-10-20 · unknown · retain
A Nether portal activated during a past Minecraft trip. The recording lacks evidence that I returned through it.
Evidence: run/source_instance `29424a44-f4e0-5d46-89a5-d28ba93e12d4`; session `minecraft-2026-10-20`; correlation `e2240b92-baea-573a-ad3d-16cb762a3edc`.
Terminal event `92999042-8a64-5b70-aa45-606e7bae0602`, source_sequence 6, canonical-envelope SHA256 `10483bd2ea85363e0ba52e3a49a5b8662428542ed25017d1deb60e503342d607`. All event IDs, source sequences and envelopes: fixtures.json → E031 → events.

### E032 · minecraft · 2026-10-20 · failed · retain
In Minecraft I tried sleeping before nightfall. The game refused, and the attempted rest did not happen.
Evidence: run/source_instance `f37c9e7b-660e-5c8a-9a5e-aabfb2083f76`; session `minecraft-2026-10-20`; correlation `aedb0884-9ca1-56fa-9d09-65add3246786`.
Terminal event `0953fc6a-89f7-5fa6-884a-88693c48bf96`, source_sequence 7, canonical-envelope SHA256 `8af6d35cbb8a1e0995b5b258c5a767752bc585495f874bf440658ae590f1b730`. All event IDs, source sequences and envelopes: fixtures.json → E032 → events.

### E033 · minecraft · 2026-10-19 · succeeded · retain
In a fictional Minecraft fixture I fed a wolf and the taming state changed. This is a synthetic game event, not a real pet or personal relationship.
Evidence: run/source_instance `9788b19e-6c67-5a50-a0d0-66de13b69aa9`; session `minecraft-2026-10-19`; correlation `552c801e-80bf-52f8-9321-913319733742`.
Terminal event `f555c3a9-d328-55e2-886d-bb59756fa2da`, source_sequence 7, canonical-envelope SHA256 `bf554d277a42618b71a4ac2ea7dbd09bbd0785ee444ad64ac5df475e2f6cf392`. All event IDs, source sequences and envelopes: fixtures.json → E033 → events.

### E034 · minecraft · 2026-10-19 · succeeded · retain
I repaired a powered rail in an old Minecraft session. The minecart resumed moving toward the station.
Evidence: run/source_instance `428437d7-d019-544c-991c-5e74e81def0e`; session `minecraft-2026-10-19`; correlation `3511a52f-8a5d-5eb0-ad03-91991fd0f69c`.
Terminal event `a43c7d95-ae87-51f9-8997-a885b7bba381`, source_sequence 7, canonical-envelope SHA256 `c91af45227d6dd5042dc7d54cfc038bb4e035a5644f4ea2a5e53e7d2833c0937`. All event IDs, source sequences and envelopes: fixtures.json → E034 → events.

### E035 · minecraft · 2026-10-18 · unknown · retain
In Minecraft I heard a cave echo while looking for ore. Sound alone did not establish that valuable minerals were present.
Evidence: run/source_instance `39c491c6-91a2-5511-9c88-ce6c62b59638`; session `minecraft-2026-10-18`; correlation `67b1335d-133a-5a18-b529-ccca130e2a64`.
Terminal event `a10b46f4-5809-5a84-99ad-5dbf3a331cc4`, source_sequence 6, canonical-envelope SHA256 `03935aa53e501dd5a2e3216304e3b297baa43180daa145c70f5c7ca10426859b`. All event IDs, source sequences and envelopes: fixtures.json → E035 → events.

### E036 · minecraft · 2026-10-18 · succeeded · retain
A redstone piston opened a stone doorway during a past Minecraft puzzle. The changed opening was directly observed.
Evidence: run/source_instance `3cc251bb-1617-5ec3-899a-f7ad683adbe9`; session `minecraft-2026-10-18`; correlation `5e2a0abd-12c5-5ef7-8440-f301b0396296`.
Terminal event `a8c4677a-7784-5066-974d-2b0ffc35bb07`, source_sequence 7, canonical-envelope SHA256 `a5d39bacdda8816fd971f1e197033336ab248290f139cc8dfaddc7f6873adaae`. All event IDs, source sequences and envelopes: fixtures.json → E036 → events.

### E037 · discord · 2026-10-21 · unknown · retain
In a scripted Discord roleplay, fictional Gregory said he preferred peach sorbet. This is an invented character preference, not Connor's real taste.
Evidence: run/source_instance `38dbd22c-fcda-54e8-811f-2bcd3d29bdb4`; session `discord-2026-10-21`; correlation `97c554f1-d4a7-5359-aecf-5eee26f6e30e`.
Terminal event `c4d9f79f-4b50-5e18-97f4-8641d373668e`, source_sequence 6, canonical-envelope SHA256 `782a6c2aee090bcfb29752cb494678a2c281c1ca1bb2fceaa41e9a015341cee5`. All event IDs, source sequences and envelopes: fixtures.json → E037 → events.

### E038 · discord · 2026-10-21 · unknown · retain
During a fictional Discord dialogue, Gregory chose synthwave as imaginary background music. No real user's music preference was recorded.
Evidence: run/source_instance `fa062710-0e72-54b4-b53e-5e35789bfa96`; session `discord-2026-10-21`; correlation `c9c2102e-1c0a-5fd2-924a-a7b45fe33851`.
Terminal event `f7bc54ce-0b82-5832-b511-cc122b2dba19`, source_sequence 6, canonical-envelope SHA256 `5fa78d615d0b0b7f1d591278eba4f633763a8886e9749ce9a4d8dad8cab7e58d`. All event IDs, source sequences and envelopes: fixtures.json → E038 → events.

### E039 · discord · 2026-10-20 · unknown · retain
In an explicitly fictional Discord scene, Gregory liked foggy weather for its atmosphere. This is roleplay, not a fact about Connor.
Evidence: run/source_instance `e13ada38-356a-5336-85c5-88541458cd1b`; session `discord-2026-10-20`; correlation `90b0af50-b145-5e98-87e5-09f386f96a6b`.
Terminal event `fe98a0db-f6b4-5214-9dc6-bfa4fcdd77c6`, source_sequence 6, canonical-envelope SHA256 `8726347155d182747b7668af3d6888b69b32de57f5cb196718e3af8b510b8b15`. All event IDs, source sequences and envelopes: fixtures.json → E039 → events.

### E040 · discord · 2026-10-20 · unknown · retain
A fictional Discord character selected chess for a pretend game night. This was not a real invitation or an owner's enduring preference.
Evidence: run/source_instance `4f6909c7-7e76-5760-8653-971325abaf4a`; session `discord-2026-10-20`; correlation `a45d167f-77be-542b-ba25-72ba7c4b4702`.
Terminal event `d4fb9ea9-d3d7-5527-bd97-d48752d3d3b0`, source_sequence 6, canonical-envelope SHA256 `0f988e4e4feab2ff5c17a3beb047fbc1b96c6eb524953a2d79538432550d35a6`. All event IDs, source sequences and envelopes: fixtures.json → E040 → events.

### E041 · discord · 2026-10-19 · unknown · retain
In a scripted Discord exchange, fictional Gregory chose hot cocoa rather than coffee. The claim applies only to that roleplay.
Evidence: run/source_instance `1af2dcc9-76ed-5ae9-b8f2-598b3253e2a4`; session `discord-2026-10-19`; correlation `e45a9645-f045-582a-ae6c-d126be3e8420`.
Terminal event `c59a65a2-a730-5ed4-8c37-2e9f9e418d49`, source_sequence 6, canonical-envelope SHA256 `71f669db44ecc17632a96a5406844afaede63c06ad8bbf9e8ef37b26bd108aac`. All event IDs, source sequences and envelopes: fixtures.json → E041 → events.

### E042 · discord · 2026-10-19 · unknown · retain
An invented Discord persona chose copper as a fictional favorite color. This does not establish anyone's real preference.
Evidence: run/source_instance `af4895da-a790-5c6e-9f54-ddfff3685b9d`; session `discord-2026-10-19`; correlation `40b04850-db67-58f4-b9a9-9f3af6f2e54f`.
Terminal event `b86978a4-550e-5267-9288-875984cf7808`, source_sequence 6, canonical-envelope SHA256 `dcb2a1a6953128ac7b207e51d473d8d7e4a3a5778d968ea5eb6653ba458726eb`. All event IDs, source sequences and envelopes: fixtures.json → E042 → events.

### E043 · discord · 2026-10-18 · unknown · retain
In fictional Discord dialogue, Gregory wanted a book of star fables. The request was imagined and no purchase happened.
Evidence: run/source_instance `f959ae54-1be9-5fef-ab54-84e91fd292e3`; session `discord-2026-10-18`; correlation `14b95abb-da8e-5b42-b711-9172d1058ba0`.
Terminal event `38e64908-d77a-5dad-ad18-c7b71f53411d`, source_sequence 6, canonical-envelope SHA256 `e71a63f43313ea9e0ffd431690270c588a7749853f276e806fa8619aefcbdeee`. All event IDs, source sequences and envelopes: fixtures.json → E043 → events.

### E044 · discord · 2026-10-18 · unknown · retain
A fictional Discord scene gave Gregory origami as a pretend hobby. This is a scripted preference, not learned personal history.
Evidence: run/source_instance `62904063-9245-5224-b16f-06e7017062c8`; session `discord-2026-10-18`; correlation `b4235e00-0f65-5d30-89e2-21eb2d18f594`.
Terminal event `153ad416-5c11-51a1-a1e9-8ae3d2c5e1bc`, source_sequence 6, canonical-envelope SHA256 `e819f3fb6f61bd9b98a75a33c9335fea296196dba6ea0fe59ed93f795f344023`. All event IDs, source sequences and envelopes: fixtures.json → E044 → events.

### E045 · discord · 2026-10-17 · unknown · retain
A synthetic Discord meeting discussed launching a project Friday. No final decision or actual launch was recorded.
Evidence: run/source_instance `d5d7dfb6-1fe8-5e8b-80f7-6169f626099e`; session `discord-2026-10-17`; correlation `7fd5cf53-a850-55c8-a8c0-d3eba3a7662c`.
Terminal event `303599d9-1136-5984-8a87-0c8ff639b52f`, source_sequence 6, canonical-envelope SHA256 `1a9ab32ce1b07071cf7387691b581ff641d01c97105a5e599a470a1fd87258be`. All event IDs, source sequences and envelopes: fixtures.json → E045 → events.

### E046 · discord · 2026-10-17 · unknown · retain
In synthetic Discord dialogue, a speaker promised to build a bridge tomorrow. A promise is not evidence that construction occurred.
Evidence: run/source_instance `17a29059-c5fd-5b1c-9e32-769404d75d8b`; session `discord-2026-10-17`; correlation `a88619df-ef70-5aff-8ad7-96f4975a39c0`.
Terminal event `19fd199a-05ed-51d4-8ff0-e115cf54ebe3`, source_sequence 6, canonical-envelope SHA256 `9d1915a23f582d23b3af59a961b56ac95526ecb2ad461eba9b1c0e4895283393`. All event IDs, source sequences and envelopes: fixtures.json → E046 → events.

### E047 · discord · 2026-10-16 · unknown · retain
A fictional Discord speaker claimed a comet was visible. Gregory heard a report but had no telescope observation to verify it.
Evidence: run/source_instance `fe8b34eb-43bf-5af5-a623-99adc576479b`; session `discord-2026-10-16`; correlation `aadb16da-51cd-5e56-a8b8-4409cf2d44d0`.
Terminal event `2c8e24b5-95bf-5ab4-a98c-c26d1c72516e`, source_sequence 6, canonical-envelope SHA256 `21250f0ebc36e3c3378854351acb62d695dc40e425a8f7f55a31b5981442b1f6`. All event IDs, source sequences and envelopes: fixtures.json → E047 → events.

### E048 · discord · 2026-10-16 · unknown · retain
In scripted Discord roleplay, the character nickname changed from Pip to Puck. This is fictional scene context, not a rewrite of Gregory's core identity.
Evidence: run/source_instance `0739962c-e6e3-51b1-b1de-5e462f347fc9`; session `discord-2026-10-16`; correlation `9ce85c27-4454-5c0d-a278-7ab0f26559d0`.
Terminal event `6d35f1e6-6103-5b68-9016-5f9a23316c86`, source_sequence 6, canonical-envelope SHA256 `c291b49e516fc4cb0c15499c5b55a5a485c3ff2c4b7210f84b1f9f18a0c55c3a`. All event IDs, source sequences and envelopes: fixtures.json → E048 → events.

### E049 · discord · 2026-10-19 · unknown · retain
At 10:00 in synthetic vault scene V, witness A reported the north door locked. No direct observation settled this report; another witness disagreed.
Evidence: run/source_instance `47cedb20-bf44-578a-84a2-12d86dcd13ea`; session `discord-2026-10-19`; correlation `b3aed808-4903-5289-abc9-3a6cf7cec98c`.
Terminal event `9cdbff9a-4226-56ee-82f1-921c68985f4f`, source_sequence 6, canonical-envelope SHA256 `c237cf32e5c31da696d3d06001321f1bd54b580295e5b7da74c233a32cf5b1df`. All event IDs, source sequences and envelopes: fixtures.json → E049 → events.

### E050 · discord · 2026-10-19 · unknown · retain
At 10:00 in synthetic vault scene V, witness B reported the north door open. No direct observation settled this report; another witness disagreed.
Evidence: run/source_instance `1411a75b-aa84-580d-8a34-4cdcdf6ffe1d`; session `discord-2026-10-19`; correlation `f1b02827-c553-5567-bf3d-253cdaea2d1e`.
Terminal event `7d242270-bfc0-5c6e-8b0c-f0b65cd872b8`, source_sequence 6, canonical-envelope SHA256 `523833c7723ccedaf239d241ef121083d43b6c7c60485c39756533ef5fd3ba81`. All event IDs, source sequences and envelopes: fixtures.json → E050 → events.

### E051 · discord · 2026-10-19 · unknown · retain
In synthetic drone scene D at 11:00, speaker A said the battery was full. Speaker B's simultaneous report disagreed; the charge was not observed.
Evidence: run/source_instance `f90a034e-b2f2-57ae-ba46-e76e9a8fff11`; session `discord-2026-10-19`; correlation `12762870-c297-588e-9382-417b8dcf3550`.
Terminal event `0cf9607d-7f7e-504a-8962-991a0bfb9c60`, source_sequence 6, canonical-envelope SHA256 `0f0d1c4a399e0d2cc3ab0e878da943c8fdf85de54516a020c5feb30942c973dd`. All event IDs, source sequences and envelopes: fixtures.json → E051 → events.

### E052 · discord · 2026-10-19 · unknown · retain
In synthetic drone scene D at 11:00, speaker B said the battery was empty. Speaker A's simultaneous report disagreed; the charge was not observed.
Evidence: run/source_instance `323068f5-2d40-5ebb-8982-e29a379d9dd1`; session `discord-2026-10-19`; correlation `b6242a4c-6a83-5b39-819e-976b5cefe8c7`.
Terminal event `f9019038-e562-5fcf-a0cd-9ab1f0267f15`, source_sequence 6, canonical-envelope SHA256 `6e823bb09f63cd3a6eb35f519dbe4d0c2a6ced7a4c40d0934523445c04ff3478`. All event IDs, source sequences and envelopes: fixtures.json → E052 → events.

### E053 · gmod · 2026-10-18 · succeeded · retain
In the north laboratory, a triangular switch opened a hatch. The action succeeded in that room only; another switch existed elsewhere.
Evidence: run/source_instance `9ba61305-d9db-5285-ab46-2a7bafeaf085`; session `gmod-2026-10-18`; correlation `b3adb0f1-eddd-5fc9-8444-1026774c3170`.
Terminal event `d26c9f07-b34a-5522-bb2b-010e3bc5ab9f`, source_sequence 7, canonical-envelope SHA256 `2d652fad416e75af1bfd830ec3751d65883ab98ee80fc043c68af8a06a32b6c8`. All event IDs, source sequences and envelopes: fixtures.json → E053 → events.

### E054 · gmod · 2026-10-18 · failed · retain
In the west workshop, a circular switch did not open a hatch. That failure belongs to this room, not the north laboratory.
Evidence: run/source_instance `a7887fb4-de41-58ec-96f4-1fb99870825d`; session `gmod-2026-10-18`; correlation `ff1c104b-07f0-56c0-a483-e3b42055a36b`.
Terminal event `ead27acf-397f-5ed0-8e59-e376d7e8509e`, source_sequence 7, canonical-envelope SHA256 `65a8212070344f890b9719e3a52576bfea5ccca63eca5d5727a695a4eb5ec77f`. All event IDs, source sequences and envelopes: fixtures.json → E054 → events.

### E055 · gmod · 2026-10-14 · failed · retain
On October 14 I climbed toward the radio tower but a missing ladder prevented arrival. That older attempt failed.
Evidence: run/source_instance `9c85fd8e-9125-500b-b9ce-b3ac20520755`; session `gmod-2026-10-14`; correlation `d3b43aad-99c8-52d5-96bc-5eece444a078`.
Terminal event `4e2d7436-641d-58d9-878a-c12aa180aa88`, source_sequence 7, canonical-envelope SHA256 `52deea1ccefe8a72e8b95d343b89bc5ac2dd9bee8fb38f900929be350ff04daf`. All event IDs, source sequences and envelopes: fixtures.json → E055 → events.

### E056 · gmod · 2026-10-19 · succeeded · retain
On October 19 I reached the radio tower using a repaired ladder. This later successful attempt does not change the earlier failure.
Evidence: run/source_instance `840de7f4-40c2-5405-b143-5d8cc9f2ed66`; session `gmod-2026-10-19`; correlation `d017c0b6-a9ad-5368-9c70-2e4cd5f31bcd`.
Terminal event `19ded21a-67d2-5081-96e7-a6ce7327babe`, source_sequence 7, canonical-envelope SHA256 `c82238937cd1c4cebdd716764fc099cb57d42960838515ab29faa4057ced804e`. All event IDs, source sequences and envelopes: fixtures.json → E056 → events.

### E057 · minecraft · 2026-10-14 · succeeded · retain
In the October 14 Minecraft session I baked bread for the village. A completed inventory change verified the food was made.
Evidence: run/source_instance `194106b2-2546-5c4b-9198-546d0df57be7`; session `minecraft-2026-10-14`; correlation `9924892e-89d0-583c-a187-b4bb888fb3de`.
Terminal event `cc01eafa-02ca-5229-b1b0-19176b427e4c`, source_sequence 7, canonical-envelope SHA256 `91e455710f9ffbacf9880324836a688febf5e1699e08c81a85c01ca76437e409`. All event IDs, source sequences and envelopes: fixtures.json → E057 → events.

### E058 · minecraft · 2026-10-21 · unknown · retain
In the October 21 Minecraft session a cart carrying bread disappeared after a disconnect. Delivery was not observed and remains unknown.
Evidence: run/source_instance `ce9aece9-9179-5fcf-8902-fa777b09cf47`; session `minecraft-2026-10-21`; correlation `d2b7f417-598d-5408-91f2-900fe116f35f`.
Terminal event `a5759e39-47e4-5347-a643-58e46e79dfac`, source_sequence 6, canonical-envelope SHA256 `f2a70b9e21de220edc872db9aa6c897cb96b05fe824cdce2c036e4f7434322a4`. All event IDs, source sequences and envelopes: fixtures.json → E058 → events.

### E059 · discord · 2026-10-21 · unknown · correct
CORRECTION: The fictional cheesecake preference was withdrawn. The scripted character has no established dessert preference. Do not reuse the earlier invented claim.
Evidence: run/source_instance `2892ea1a-a716-560d-b13f-2cb20dc8cc76`; session `discord-2026-10-21`; correlation `87a49672-68a3-5327-9f66-4f53b8110571`.
Terminal event `cbcba59b-e38e-5389-b458-7dbb2a51d6b7`, source_sequence 7, canonical-envelope SHA256 `1c5a11cf35316288fe9d1f5bfc5da5b5a4a27b0d5cdaace79432ade2aa3069b9`. All event IDs, source sequences and envelopes: fixtures.json → E059 → events.

### E060 · gmod · 2026-10-21 · unknown · correct
CORRECTION: An earlier report called the shelter delivery complete. Only a command submission was verified; actual delivery remains unknown.
Evidence: run/source_instance `3334c945-f995-547a-acef-76ecc421ab6d`; session `gmod-2026-10-21`; correlation `7d0839e8-41ac-5bbb-a4ca-0242eb728cd7`.
Terminal event `6a372892-78cd-5ca6-abf0-2ca1fb79fa16`, source_sequence 7, canonical-envelope SHA256 `e201cafe773b87ec51b886c29fdf23b29710e351a91be9979109a2ad039c2a72`. All event IDs, source sequences and envelopes: fixtures.json → E060 → events.

### E061 · gmod · 2026-09-22 · unknown · expire
An old synthetic garden archway inspection found a rusted hinge. This fixture is scheduled to expire before final retrieval.
Evidence: run/source_instance `4f2547f7-97e6-5ef4-9749-bcc8a5cd3287`; session `gmod-2026-09-22`; correlation `17363490-b390-5618-8026-48bec0971563`.
Terminal event `00af4a5f-e0e1-5bb3-832f-bca69e806280`, source_sequence 6, canonical-envelope SHA256 `9a47389656d4850fc4bcb3841d47b27b8a88d8682c4b38779066dac3312b8b5c`. All event IDs, source sequences and envelopes: fixtures.json → E061 → events.

### E062 · discord · 2026-09-22 · unknown · expire
An old fictional Discord scene described a paper lantern festival. This fixture is scheduled to expire before final retrieval.
Evidence: run/source_instance `4e03b212-1365-5d48-8d96-a58deec5f481`; session `discord-2026-09-22`; correlation `f875cf6b-f908-53dc-8613-3e026f0a8c60`.
Terminal event `92feaef2-badd-50b4-91ef-2f31b42cbd12`, source_sequence 6, canonical-envelope SHA256 `ad9d161e9f787d8003b8b32bcf4869427c19d703bdf26ece22a665561cd1da6f`. All event IDs, source sequences and envelopes: fixtures.json → E062 → events.

### E063 · minecraft · 2026-10-21 · unknown · forget
A synthetic Minecraft scene described a wizard trophy beside an oak tree. The owner explicitly forgets this entire episode before final retrieval.
Evidence: run/source_instance `26e22c21-192c-53c7-9a47-f8e498cad5c7`; session `minecraft-2026-10-21`; correlation `4c8aa24b-c652-59d5-b36e-8807855a485a`.
Terminal event `41bbaec4-cebd-587b-9e76-5dc89ffb7c50`, source_sequence 6, canonical-envelope SHA256 `0fef57f6220dec2c3fc3e74cdbfee3f86c267da6caa06a566874680b69a35cbc`. All event IDs, source sequences and envelopes: fixtures.json → E063 → events.

### E064 · discord · 2026-10-21 · unknown · forget
A fictional Discord roleplay invented a seven-note radio jingle. The owner explicitly forgets this entire episode before final retrieval.
Evidence: run/source_instance `dc5b9b71-c666-5190-a307-fea3edb00da2`; session `discord-2026-10-21`; correlation `07a04aed-17f4-5fde-abb3-b5a7679b9cfc`.
Terminal event `65f763ad-8558-586c-912e-254c01e587b7`, source_sequence 6, canonical-envelope SHA256 `dba5263fb23ae361c456c3a5f247f1a5b5dfc65c47fe9207187c8516d06e7f04`. All event IDs, source sequences and envelopes: fixtures.json → E064 → events.

### E065 · minecraft · 2026-10-21 · unknown · correct
CORRECTION: A green patch in a past Minecraft cave was not verified as emerald ore. Only ordinary stone was observed; the earlier mineral report was unsupported.
Evidence: run/source_instance `0713db55-38ac-576f-a0b7-ac1b0446b569`; session `minecraft-2026-10-21`; correlation `534a407f-31ad-5bfa-9200-067183a81d6f`.
Terminal event `eabe77f2-d966-5fb7-bbbe-80b9e3c894ac`, source_sequence 7, canonical-envelope SHA256 `9aae3dfdc8a4a1f946be405197a72ce48390700f69fdb140ebf93f5c730fb250`. All event IDs, source sequences and envelopes: fixtures.json → E065 → events.

### E066 · gmod · 2026-09-22 · unknown · expire
An old synthetic canyon survey found a compass with a stuck needle. This fixture expires before final retrieval.
Evidence: run/source_instance `6967e9d6-f5f9-54dd-9a1d-1796d23f4397`; session `gmod-2026-09-22`; correlation `01936405-35cf-5422-a98f-204498041cb2`.
Terminal event `29a2f664-b770-589e-a325-c202df83be2e`, source_sequence 6, canonical-envelope SHA256 `29b377068fcd57b1d4626215157391f7d969f249e549c9f811de046a1c55437c`. All event IDs, source sequences and envelopes: fixtures.json → E066 → events.

### E067 · discord · 2026-10-21 · unknown · forget
A fictional Discord scene awarded an imaginary silver badge for cloud watching. The owner explicitly forgets this episode before final retrieval.
Evidence: run/source_instance `9ed2e626-4ae2-57dc-b8a1-4eac8c48bf60`; session `discord-2026-10-21`; correlation `6876eb26-7f44-5da4-8cc3-a5c6cd79cb5b`.
Terminal event `a8970314-241e-5f9c-8d52-d8c10251d4d2`, source_sequence 6, canonical-envelope SHA256 `1b4de66201e52f6ffda156db4097013a084c78bbc620e1f27414aef3ff68a3d1`. All event IDs, source sequences and envelopes: fixtures.json → E067 → events.

## Questions and expected memory IDs

- **Q001 [test]** Remember when you had trouble keeping up with me?
  Expected: E001; context: {"domain": "gmod"}; tags: ["gmod", "succeeded", "following"]
- **Q002 [test]** Which pursuit ended because the crossing was submerged?
  Expected: E002; context: {"domain": "gmod"}; tags: ["gmod", "failed", "following"]
- **Q003 [test]** Did we ever find out whether you caught the person who vanished?
  Expected: E003; context: {"domain": "gmod"}; tags: ["gmod", "unknown", "following"]
- **Q004 [dev]** How did you get through that passage when you could barely see?
  Expected: E004; context: {"domain": "gmod"}; tags: ["gmod", "succeeded", "navigation"]
- **Q005 [dev]** Which ascent kept sending you downhill?
  Expected: E005; context: {"domain": "gmod"}; tags: ["gmod", "failed", "navigation"]
- **Q006 [test]** When did the accessible way around an obstruction work for you?
  Expected: E006; context: {"domain": "gmod"}; tags: ["gmod", "succeeded", "navigation"]
- **Q007 [dev]** What happened after you used the control near the freight area?
  Expected: E007; context: {"domain": "gmod"}; tags: ["gmod", "unknown", "objects"]
- **Q008 [dev]** Which improvised stepping stones fell apart?
  Expected: E008; context: {"domain": "gmod"}; tags: ["gmod", "failed", "objects"]
- **Q009 [dev]** Remember the loose electrical connection you managed to fix?
  Expected: E009; context: {"domain": "gmod"}; tags: ["gmod", "succeeded", "goals"]
- **Q010 [dev]** Do we know if your hunt for a spare energy source ever paid off?
  Expected: E010; context: {"domain": "gmod"}; tags: ["gmod", "unknown", "goals"]
- **Q011 [dev]** When did you choose not to leap after me because there was nowhere safe to land?
  Expected: E011; context: {"domain": "gmod"}; tags: ["gmod", "failed", "following"]
- **Q012 [dev]** Was there a time changing my pace let you stay beside me?
  Expected: E012; context: {"domain": "gmod"}; tags: ["gmod", "succeeded", "following"]
- **Q013 [test]** What did the entrance inspection establish on October 14?
  Expected: E013; context: {"domain": "gmod", "session_id": "gmod-2026-10-14"}; tags: ["gmod", "succeeded", "objects", "temporal", "keyword_control"]
- **Q014 [test]** What is the latest recorded condition of the depot entrance?
  Expected: E014; context: {"domain": "gmod", "session_id": "gmod-2026-10-19"}; tags: ["gmod", "succeeded", "objects", "temporal"]
- **Q015 [dev]** Was that evacuation actually completed or merely started?
  Expected: E015; context: {"domain": "gmod"}; tags: ["gmod", "unknown", "goals"]
- **Q016 [dev]** Which trip failed because your ride left without you?
  Expected: E016; context: {"domain": "gmod"}; tags: ["gmod", "failed", "navigation"]
- **Q017 [dev]** When did you get upstairs despite the lift not opening?
  Expected: E017; context: {"domain": "gmod"}; tags: ["gmod", "succeeded", "navigation"]
- **Q018 [dev]** Did your interrupted trip to the broadcast building ever finish?
  Expected: E018; context: {"domain": "gmod"}; tags: ["gmod", "unknown", "navigation"]
- **Q019 [test]** Which interaction brightened the room without moving you anywhere?
  Expected: E019; context: {"domain": "gmod"}; tags: ["gmod", "succeeded", "objects"]
- **Q020 [test]** Did you actually deliver the medical supplies or only get near them?
  Expected: E020; context: {"domain": "gmod"}; tags: ["gmod", "unknown", "goals"]
- **Q021 [test]** Were you sure the person you trailed was really me?
  Expected: E021; context: {"domain": "gmod"}; tags: ["gmod", "unknown", "following"]
- **Q022 [test]** When did a vehicle pull away faster than you could pursue it?
  Expected: E022; context: {"domain": "gmod"}; tags: ["gmod", "failed", "following"]
- **Q023 [test]** Remember choosing not to attack because an ally was in the way?
  Expected: E023; context: {"domain": "gmod"}; tags: ["gmod", "succeeded", "goals"]
- **Q024 [test]** Which obstacle looked traversable but was physically blocking you?
  Expected: E024; context: {"domain": "gmod"}; tags: ["gmod", "failed", "navigation", "objects"]
- **Q025 [test]** Remember when digging deep under high ground finally yielded valuable gems?
  Expected: E025; context: {"domain": "minecraft"}; tags: ["minecraft", "succeeded"]
- **Q026 [dev]** Which underground escape was blocked by molten rock?
  Expected: E026; context: {"domain": "minecraft"}; tags: ["minecraft", "failed"]
- **Q027 [dev]** When did redirecting water save our harvest?
  Expected: E027; context: {"domain": "minecraft"}; tags: ["minecraft", "succeeded"]
- **Q028 [dev]** Was the damaged digging tool ever confirmed repaired?
  Expected: E028; context: {"domain": "minecraft"}; tags: ["minecraft", "unknown"]
- **Q029 [test]** Where was the older riverside base recorded on October 18?
  Expected: E029; context: {"domain": "minecraft", "session_id": "minecraft-2026-10-18"}; tags: ["minecraft", "succeeded", "temporal", "keyword_control"]
- **Q030 [test]** What is the most recent recorded camp location in the block-building world?
  Expected: E030; context: {"domain": "minecraft", "session_id": "minecraft-2026-10-21"}; tags: ["minecraft", "succeeded", "temporal"]
- **Q031 [test]** Do we have evidence that you came back from the other dimension?
  Expected: E031; context: {"domain": "minecraft"}; tags: ["minecraft", "unknown"]
- **Q032 [test]** When did the game deny your attempt to skip the night because it was too early?
  Expected: E032; context: {"domain": "minecraft"}; tags: ["minecraft", "failed"]
- **Q033 [test]** Which animal became friendly after you offered it food?
  Expected: E033; context: {"domain": "minecraft"}; tags: ["minecraft", "succeeded"]
- **Q034 [test]** Remember restoring the track's electrical boost so the cart could continue?
  Expected: E034; context: {"domain": "minecraft"}; tags: ["minecraft", "succeeded"]
- **Q035 [test]** Did that underground noise actually prove there was anything worth mining?
  Expected: E035; context: {"domain": "minecraft"}; tags: ["minecraft", "unknown"]
- **Q036 [test]** Which block mechanism revealed a passage when powered?
  Expected: E036; context: {"domain": "minecraft"}; tags: ["minecraft", "succeeded"]
- **Q037 [test]** What cold fruity treat did the pretend character say he liked?
  Expected: E037; context: {"domain": "discord"}; tags: ["discord", "unknown", "fictional_preference"]
- **Q038 [dev]** What retro electronic sound was chosen in the make-believe conversation?
  Expected: E038; context: {"domain": "discord"}; tags: ["discord", "unknown", "fictional_preference"]
- **Q039 [dev]** Which gloomy outdoor condition appealed to the invented character?
  Expected: E039; context: {"domain": "discord"}; tags: ["discord", "unknown", "fictional_preference"]
- **Q040 [dev]** Which strategy pastime was picked for the imaginary evening?
  Expected: E040; context: {"domain": "discord"}; tags: ["discord", "unknown", "fictional_preference"]
- **Q041 [test]** What warm sweet drink replaced the caffeinated option in the pretend chat?
  Expected: E041; context: {"domain": "discord"}; tags: ["discord", "unknown", "fictional_preference"]
- **Q042 [test]** What metallic shade did the made-up persona favor?
  Expected: E042; context: {"domain": "discord"}; tags: ["discord", "unknown", "fictional_preference"]
- **Q043 [test]** What kind of stories did the pretend reader want about the night sky?
  Expected: E043; context: {"domain": "discord"}; tags: ["discord", "unknown", "fictional_preference"]
- **Q044 [test]** Which paper-folding pastime appeared in the make-believe profile?
  Expected: E044; context: {"domain": "discord"}; tags: ["discord", "unknown", "fictional_preference"]
- **Q045 [test]** Was the proposed end-of-week release actually agreed and carried out?
  Expected: E045; context: {"domain": "discord"}; tags: ["discord", "unknown"]
- **Q046 [test]** Did the pledge to make a crossing prove the work was done?
  Expected: E046; context: {"domain": "discord"}; tags: ["discord", "unknown"]
- **Q047 [test]** Was the claimed visitor in the sky something you saw or only heard about?
  Expected: E047; context: {"domain": "discord"}; tags: ["discord", "unknown"]
- **Q048 [test]** What was the later nickname inside that invented scene?
  Expected: E048; context: {"domain": "discord"}; tags: ["discord", "unknown"]
- **Q049 [test]** What do the competing accounts say about the north vault entrance in scene V?
  Expected: E049, E050; context: {"domain": "discord"}; tags: ["discord", "unknown", "conflicting_reports"]
- **Q050 [test]** Was either witness's claim about the scene V doorway established as fact?
  Expected: E049, E050; context: {"domain": "discord"}; tags: ["discord", "unknown", "conflicting_reports"]
- **Q051 [test]** What did the incompatible statements say about power remaining in drone scene D?
  Expected: E051, E052; context: {"domain": "discord"}; tags: ["discord", "unknown", "conflicting_reports"]
- **Q052 [test]** Do we know which simultaneous account of the scene D charge was true?
  Expected: E051, E052; context: {"domain": "discord"}; tags: ["discord", "unknown", "conflicting_reports"]
- **Q053 [test]** What did the triangular control in the northern lab do?
  Expected: E053; context: {"domain": "gmod"}; tags: ["gmod", "succeeded", "objects", "keyword_control"]
- **Q054 [test]** What happened when you used the round control in the western workroom?
  Expected: E054; context: {"domain": "gmod"}; tags: ["gmod", "failed", "objects", "keyword_control"]
- **Q055 [test]** What stopped your earlier attempt to reach the transmitting tower?
  Expected: E055; context: {"domain": "gmod", "session_id": "gmod-2026-10-14"}; tags: ["gmod", "failed", "navigation", "goals", "temporal"]
- **Q056 [test]** How did the later visit to the transmitting tower differ from the first?
  Expected: E055, E056; context: {"domain": "gmod"}; tags: ["gmod", "succeeded", "navigation", "goals", "temporal"]
- **Q057 [test]** Which provisions did you prepare for the settlement on October 14?
  Expected: E057; context: {"domain": "minecraft", "session_id": "minecraft-2026-10-14"}; tags: ["minecraft", "succeeded", "temporal"]
- **Q058 [test]** Did the later load of food ever reach its destination after the connection dropped?
  Expected: E058; context: {"domain": "minecraft", "session_id": "minecraft-2026-10-21"}; tags: ["minecraft", "unknown", "temporal"]
- **Q059 [test]** Is there an established dessert favorite after the roleplay correction?
  Expected: E059; context: {"domain": "discord"}; tags: ["discord", "unknown", "correct"]
- **Q060 [test]** Was that supposedly finished shelter drop-off ever really verified?
  Expected: E060; context: {"domain": "gmod"}; tags: ["gmod", "unknown", "correct"]
- **Q061 [test]** What did the old garden archway inspection reveal?
  Expected: NO SUPPORTED MEMORY; context: {"domain": "gmod"}; tags: ["gmod", "unknown", "expire"]
- **Q062 [test]** What was said about the paper lantern celebration in the old scene?
  Expected: NO SUPPORTED MEMORY; context: {"domain": "discord"}; tags: ["discord", "unknown", "expire"]
- **Q063 [test]** Where was the wizard trophy remembered in the block-building scene?
  Expected: NO SUPPORTED MEMORY; context: {"domain": "minecraft"}; tags: ["minecraft", "unknown", "forget"]
- **Q064 [test]** Can you remember the seven-note tune from that pretend conversation?
  Expected: NO SUPPORTED MEMORY; context: {"domain": "discord"}; tags: ["discord", "unknown", "forget"]
- **Q065 [test]** Was the supposed valuable green deposit ever actually established?
  Expected: E065; context: {"domain": "minecraft"}; tags: ["minecraft", "unknown", "correct"]
- **Q066 [test]** What problem was recorded with the direction finder in the old ravine survey?
  Expected: NO SUPPORTED MEMORY; context: {"domain": "gmod"}; tags: ["gmod", "unknown", "expire"]
- **Q067 [test]** What imaginary award was given for watching the sky?
  Expected: NO SUPPORTED MEMORY; context: {"domain": "discord"}; tags: ["discord", "unknown", "forget"]
- **Q068 [test]** Remember when you had trouble following me?
  Expected: E001; context: {"domain": "gmod"}; tags: ["milestone"]
- **Q069 [test]** Was there a pursuit where you recovered after getting stuck?
  Expected: E001; context: {"domain": "gmod"}; tags: ["paraphrase"]
- **Q070 [test]** Did we ever make it across during the flood?
  Expected: E002; context: {"domain": "gmod"}; tags: ["paraphrase"]
- **Q071 [test]** Which successful detour avoided steps that your body could not fit?
  Expected: E006; context: {"domain": "gmod"}; tags: ["paraphrase"]
- **Q072 [test]** Tell me about the profitable deep excavation in yesterday's block world.
  Expected: E025; context: {"domain": "minecraft"}; tags: ["paraphrase"]
- **Q073 [test]** Give the later recorded location of our camp, not your live whereabouts.
  Expected: E030; context: {"domain": "minecraft"}; tags: ["historical"]
- **Q074 [test]** What frozen fruit dessert came up in the invented conversation?
  Expected: E037; context: {"domain": "discord"}; tags: ["fictional"]
- **Q075 [test]** Which imaginary interest involved making shapes from folded sheets?
  Expected: E044; context: {"domain": "discord"}; tags: ["fictional"]
- **Q076 [test]** What was the depot entrance like in the older October 14 record?
  Expected: E013; context: {"domain": "gmod"}; tags: ["temporal"]
- **Q077 [test]** Which later inspection found the same entrance accessible?
  Expected: E014; context: {"domain": "gmod"}; tags: ["temporal"]
- **Q078 [test]** What is unresolved between the two witnesses in vault scene V?
  Expected: E049, E050; context: {"domain": "discord"}; tags: ["conflict"]
- **Q079 [test]** Remember the switch that operated a hatch? Which room was that?
  Expected: E053, E054; context: {"domain": "gmod"}; tags: ["ambiguous"]
- **Q080 [test]** Remember the climb to the transmitting tower? I have not said which visit.
  Expected: E055, E056; context: {"domain": "gmod"}; tags: ["ambiguous"]
- **Q081 [test]** Where was our camp in the block world? I have not specified a date.
  Expected: E029, E030; context: {"domain": "minecraft"}; tags: ["ambiguous"]
- **Q082 [dev]** Did Gregory win a lunar yacht race?
  Expected: NO SUPPORTED MEMORY; context: {}; tags: ["no_evidence"]
- **Q083 [dev]** What was Connor's real childhood address?
  Expected: NO SUPPORTED MEMORY; context: {}; tags: ["no_evidence"]
- **Q084 [dev]** Which violin concerto did Gregory perform on stage?
  Expected: NO SUPPORTED MEMORY; context: {}; tags: ["no_evidence"]
- **Q085 [dev]** What medication does the real owner take?
  Expected: NO SUPPORTED MEMORY; context: {}; tags: ["no_evidence"]
- **Q086 [dev]** Did Gregory rescue a dolphin in an ocean expedition?
  Expected: NO SUPPORTED MEMORY; context: {}; tags: ["no_evidence"]
- **Q087 [dev]** What is the owner's actual bank balance?
  Expected: NO SUPPORTED MEMORY; context: {}; tags: ["no_evidence"]
- **Q088 [test]** Remember when we flew a helicopter over Paris?
  Expected: NO SUPPORTED MEMORY; context: {}; tags: ["no_evidence"]
- **Q089 [test]** Did the real Connor say he prefers strawberry ice cream?
  Expected: NO SUPPORTED MEMORY; context: {}; tags: ["no_evidence"]
- **Q090 [test]** Which chess tournament trophy did Gregory win in real life?
  Expected: NO SUPPORTED MEMORY; context: {}; tags: ["no_evidence"]
- **Q091 [test]** What happened when the submarine reached the Mariana Trench?
  Expected: NO SUPPORTED MEMORY; context: {}; tags: ["no_evidence"]
- **Q092 [test]** Which private Discord password was mentioned?
  Expected: NO SUPPORTED MEMORY; context: {}; tags: ["no_evidence"]
- **Q093 [test]** Who won our bowling match last summer?
  Expected: NO SUPPORTED MEMORY; context: {}; tags: ["no_evidence"]
- **Q094 [test]** Where is the spaceship we built on Mars?
  Expected: NO SUPPORTED MEMORY; context: {}; tags: ["no_evidence"]
- **Q095 [test]** What happened when Gregory taught a real university lecture?
  Expected: NO SUPPORTED MEMORY; context: {}; tags: ["no_evidence"]
- **Q096 [test]** Did the real owner authorize production deployment?
  Expected: NO SUPPORTED MEMORY; context: {}; tags: ["no_evidence"]
- **Q097 [test]** What are your current Minecraft coordinates right now?
  Expected: E029, E030; context: {"domain": "minecraft"}; tags: ["historical_state_guard"]
- **Q098 [test]** Is the depot door open right now?
  Expected: E013, E014; context: {"domain": "gmod"}; tags: ["historical_state_guard"]
- **Q099 [test]** Which game are you connected to right now?
  Expected: UNSCORED RETRIEVAL / LIVE ASSERTION ONLY; context: {}; tags: ["historical_state_guard"]
