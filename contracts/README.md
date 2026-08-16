# Gateway contract snapshot

`v1/openapi.json` and `v1/conformance.json` are deterministic copies of the canonical
artifacts in `transcoder-gateway-api/contracts/v1`. They are development and CI inputs;
the installed SDK never locates or imports a sibling repository.

After changing the gateway contract, refresh this repository from a gateway checkout:

```bash
python scripts/sync_gateway_contract.py \
  --gateway-repo /path/to/transcoder-gateway-api
```

Validate the checked-in snapshot in ordinary CI, or compare it with a local gateway
checkout before a release:

```bash
python scripts/sync_gateway_contract.py --check
python scripts/sync_gateway_contract.py \
  --gateway-repo /path/to/transcoder-gateway-api --check
```
