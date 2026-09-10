# KRONOS ALPHA Authenticity Audit V2

Verified: 2026-07-11  
Result: **PASSED**

## Pinned identities

- Official source: `https://github.com/shiyu-coder/Kronos`
- Source revision: `67b630e67f6a18c9e9be918d9b4337c960db1e9a`
- Model: `NeoQuasar/Kronos-small`
- Model revision: `901c26c1332695a2a8f243eb2f37243a37bea320`
- Tokenizer: `NeoQuasar/Kronos-Tokenizer-base`
- Tokenizer revision: `0e0117387f39004a9016484a186a908917e22426`
- License: MIT

## Local evidence

| Artifact | Bytes | SHA-256 |
|---|---:|---|
| Model `model.safetensors` | 98,980,656 | `b082dfcbd8e8c142a725c8bbb99781802f38fec81210e13479effb32b3c3e020` |
| Model `config.json` | 228 | `5e0f6a605d5f81b5c9b559fe5cf716a1acb041c744e6f41bd05b097b7a685396` |
| Tokenizer `model.safetensors` | 15,842,368 | `59d85f6af76a2c3b8240ea06cb21db4213b4eeca053f246b23e29cf832fc6bee` |
| Tokenizer `config.json` | 301 | `2366e7ccfec76cbc19cf3c4c1b9c5d901be336ca1e83f2d2292c9bff381b77a2` |

- Kronos-small parameters measured locally: 24,741,376.
- Tokenizer parameters measured locally: 3,958,042.
- Model architecture config: 8 layers, 512 model width, 8 attention heads, 1,024 feed-forward width, 10+10 token bits.
- Tokenizer config: six input fields, 256 model width, four encoder/four decoder layers, four heads.
- Both artifacts loaded from pinned local snapshot directories with `HF_HUB_OFFLINE=1`.
- Genuine local forecasts completed on MPS and offline reload tests passed.
- The runner imports model implementation only from the pinned official source checkout and loads local snapshot paths. It never enables Hugging Face remote custom code.
- No unpinned download, lookalike model, Amazon Chronos package, or remote-code substitution exists.

Any future hash, revision, config-identity, or size mismatch must leave KRONOS ALPHA inactive until a new explicit authenticity audit passes.
