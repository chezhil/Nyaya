# NYAYA agent rules
1. Only edit the folders your owner assigned you (see CONTRACTS.md "Ownership"). Never touch other folders.
2. Follow CONTRACTS.md interfaces exactly. If you need a change, stop and ask your human.
3. Never invent, hard-code or "placeholder" metrics, scenario outcomes or benchmark numbers. All numbers come from running code.
4. Train and save models ONLY on the LinuxONE server (big-endian). Use `import torch` (never `import torch_nnpa`).
   Only these libraries: xgboost, scikit-learn, torch, numpy, pandas, networkx, rank-bm25, llama_cpp, fastapi, uvicorn, pycryptodome. No lightgbm/onnxruntime/shap.
5. Never commit secrets, *.pem, .env, tokens, raw data, artifacts/ or *.gguf.
6. Small commits with conventional messages (feat(engine): ...). Run tests before committing.
7. No real personal data. All data is synthetic or public (PaySim, OpenFEMA).
8. Claim NNPA/Telum acceleration only where a measurement shows it.
