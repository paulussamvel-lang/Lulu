# Recording-wide speaker component

CAM++ is an auxiliary speaker embedding model from FunASR, Apache-2.0.
Source: https://huggingface.co/funasr/campplus
Revision: `e4b6ede7ce16997aff4ae69fbca1f0175e2afede`
File: `campplus_cn_common.bin`, 28,036,335 bytes
SHA-256: `3388cf5fd3493c9ac9c69851d8e7a8badcfb4f3dc631020c4961371646d5ada8`

Place the verified file in `app/build/global-speakers/` before building.
Only this small auxiliary model is bundled. Existing ASR/TTS model files and
user documents are unchanged. Runtime is offline, uses an owned CPU child,
loads the state dictionary with `weights_only=True`, and never loads remote code.
Acoustic matches are estimates. Turns without sufficient clean speech remain
unassigned and render as “发言人待确认”; they are never assigned by speaking order.
