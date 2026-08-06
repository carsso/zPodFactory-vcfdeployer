# VCF Deployer Config Script for zPodFactory

This is a config-script for [zPodFactory](https://github.com/zPodFactory/zpodcore) that
turns a zPod into a full VMware Cloud Foundation instance. Once the `vcfinstaller`
component is deployed, it hands the zPod over to
[zpod-vcf-deployer](https://github.com/zPodFactory/zpod-vcf-deployer) (vendored here as a
git submodule), which runs the rest of the VCF pipeline: DNS records, depot setup, bundle
downloads, SDDC validation and SDDC deployment.

This config-script follows zPodFactory's config-scripts architecture as introduced in
[PR #43](https://github.com/zPodFactory/zpodcore/pull/43) and
[PR #47](https://github.com/zPodFactory/zpodcore/pull/47).

## Overview

`zpod_component_add_vcfinstaller.py` runs at the end of the `vcfinstaller` component add,
and invokes:

```bash
uv run zpod-vcf-deployer.py -n <zpod name> -j config/<zpod profile>.json --debug
```

The VCF JSON template is derived from the **zPod profile name**, so a zPod deployed with
the `v9.1.0.0_std_3hosts` profile uses `zpod-vcf-deployer/config/v9.1.0.0_std_3hosts.json`.
Name your zPodFactory profiles after the deployer templates:

| Template | zPod profile name to use |
|----------|--------------------------|
| `config/v9.0.0.0_std_3hosts.json` | `v9.0.0.0_std_3hosts` |
| `config/v9.0.1.0_std_3hosts.json` | `v9.0.1.0_std_3hosts` |
| `config/v9.0.1.0_std_4hosts.json` | `v9.0.1.0_std_4hosts` |
| `config/v9.0.2.0_std_3hosts.json` | `v9.0.2.0_std_3hosts` |
| `config/v9.1.0.0_std_3hosts.json` | `v9.1.0.0_std_3hosts` |
| `config/v9.1-latest_std_3hosts.json` | `v9.1-latest_std_3hosts` |

If no template matches the zPod profile, the config script fails early with an explicit
error rather than starting a doomed deployment.

The zPod is flagged `ACTIVE` for the duration of the run: the deployer talks to the
zPodFactory API and only creates a zPod when it is not `ACTIVE` yet, so without this it
would deploy a second zPod under the same name. The original status is restored when the
deployer returns, so a failed VCF deployment still ends up as `DEPLOY_FAILED`.

Note that a VCF deployment takes around 2h30, and the `vcfinstaller` component add stays
in `CONFIG_SCRIPTS` for that whole time.

## Usage

### Clone the repository into the `config-scripts` directory

In the `zpodcore` directory, run:
```bash
git clone --recurse-submodules https://github.com/carsso/zPodFactory-vcfdeployer.git zpodengine/src/zpodengine/config_scripts/vcfdeployer
```

If you cloned without `--recurse-submodules`, pull the deployer in with:
```bash
git submodule update --init
```

### Configure the deployer

Create your `.env` file from the example and fill it in:

```bash
cd zpodengine/src/zpodengine/config_scripts/vcfdeployer
cp env_example.txt .env
```

| Variable | Description |
|----------|-------------|
| `ZPODFACTORY_BASE_URL` | zPodFactory API URL (e.g. `http://zpodfactory.example.com:8000`) |
| `ZPODFACTORY_ACCESS_TOKEN` | Your zPodFactory API access token |
| `ZPODFACTORY_DEFAULT_ENDPOINT` | zPodFactory endpoint name |
| `ZPODFACTORY_DEFAULT_PROFILE` | Required by the deployer CLI, unused here (the zPod already exists) |
| `VCF_DEPOT_MODE` | `online` or `offline` (VCF 9.1+ requires `offline`) |

Plus the depot credentials matching the chosen mode. See
[zpod-vcf-deployer](https://github.com/zPodFactory/zpod-vcf-deployer#environment-variables)
for the full list. These settings can also be passed as environment variables of the
zpodengine worker instead of a `.env` file.

### Set as global default configuration

You can configure this as a default config-script for all new zPods using the
`ff_default_config_scripts` setting:

In the `zpodcore` directory, run:
```bash
# Set default config-scripts (comma-separated)
just zcli setting create -n ff_default_config_scripts -v "vcfdeployer" -d ""
```

### Updating the deployer

The deployer is pinned to a specific commit. To move to the latest version:

```bash
git submodule update --remote zpod-vcf-deployer
git commit -am "Bump zpod-vcf-deployer"
```
