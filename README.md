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
uv run zpod-vcf-deployer.py \
  -n <zpod name> \
  -j config/<zpod profile>.json \
  -p <zpod profile> \
  -e <endpoint name> \
  -u http://<zpodfactory_host setting>:8000 \
  -a <api token>
```

Everything on that command line is read from the zPod and from the zPodFactory database,
so nothing has to be duplicated in a config file:

| Option | Source |
|--------|--------|
| `-n` | `zpod.name` |
| `-j` | `zpod.profile`, as an absolute path (see below) |
| `-p` | `zpod.profile` — required by the deployer CLI, unused since the zPod already exists |
| `-e` | `zpod.endpoint.name` |
| `-u` | `zpodfactory_host` setting, port 8000 (override with `ZPODFACTORY_BASE_URL`) |
| `-a` | API token of the zPod owner, falling back to a superadmin if that account is disabled |

Set `VCF_DEPLOYER_DEBUG=true` in the `.env` to append `--debug` and get the API payloads
and responses in the flow logs. It is off by default, like in the deployer itself.

The deployer runs in its own Prefect task, failed after 12 hours by default. Set
`VCF_DEPLOYER_TIMEOUT` (in seconds) in the `.env` to change that.

The VCF JSON template is derived from the **zPod profile name**, so a zPod deployed with
the `v9.1.0.0_std_3hosts` profile uses `v9.1.0.0_std_3hosts.json`. It is looked up in two
places, in order:

1. `config/` at the root of this config script — your **custom templates**
2. `zpod-vcf-deployer/config/` — the templates the deployer ships

so you can override a bundled template, or add one for a profile the deployer does not
cover, without ever touching the submodule. Which file was picked is printed in the flow
logs. Name your zPodFactory profiles after the templates:

| Template shipped by the deployer | zPod profile name to use |
|----------|--------------------------|
| `v9.0.0.0_std_3hosts.json` | `v9.0.0.0_std_3hosts` |
| `v9.0.1.0_std_3hosts.json` | `v9.0.1.0_std_3hosts` |
| `v9.0.1.0_std_4hosts.json` | `v9.0.1.0_std_4hosts` |
| `v9.0.2.0_std_3hosts.json` | `v9.0.2.0_std_3hosts` |
| `v9.1.0.0_std_3hosts.json` | `v9.1.0.0_std_3hosts` |
| `v9.1-latest_std_3hosts.json` | `v9.1-latest_std_3hosts` |

A custom template is just a copy you edit:

```bash
mkdir -p config
cp zpod-vcf-deployer/config/v9.1.0.0_std_3hosts.json config/vcf-910-lab.json
# ... edit, then create a zPodFactory profile named vcf-910-lab
```

If no template matches the zPod profile in either directory, the config script fails early
with an explicit error rather than starting a doomed deployment.

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
git clone https://github.com/carsso/zPodFactory-vcfdeployer.git zpodengine/src/zpodengine/config_scripts/vcfdeployer
cd zpodengine/src/zpodengine/config_scripts/vcfdeployer
git submodule update --init --remote
```

`--remote` checks out the deployer's latest `main` rather than the commit recorded here.

### Configure the VCF depot

The zPodFactory side needs no configuration, only the VCF depot does. Start from the
deployer's own example and fill in the depot section:

```bash
cd zpodengine/src/zpodengine/config_scripts/vcfdeployer
cp zpod-vcf-deployer/env_example.txt .env
```

| Variable | Description |
|----------|-------------|
| `VCF_DEPOT_MODE` | `online` or `offline` (VCF 9.1+ requires `offline`) |
| `VCF_OFFLINE_DEPOT_HOSTNAME` / `_USERNAME` / `_PASSWORD` / `_PORT` | Offline depot, when `VCF_DEPOT_MODE=offline` |
| `VCF_ONLINE_DEPOT_DOWNLOAD_TOKEN` | Broadcom download token, when `VCF_DEPOT_MODE=online` |
| `VCF_DEPLOYER_DEBUG` | Optional, `true` to run the deployer with `--debug`. Read by this config script, not by the deployer |
| `VCF_DEPLOYER_TIMEOUT` | Optional, Prefect timeout of the deployer run in seconds (default 43200). Read by this config script |

The `ZPODFACTORY_*` and `VCF_JSON_TEMPLATE` entries of that example are dead weight here:
the config script passes all of them on the command line, and a CLI option always wins
over the matching environment variable. Leave them as they are, or strip them out.

The `.env` goes at the config script root rather than inside the submodule, so that
updating the deployer never touches it. python-dotenv walks up from the deployer script
and finds it there. See
[zpod-vcf-deployer](https://github.com/zPodFactory/zpod-vcf-deployer#environment-variables)
for the details of each setting. They can also be passed as environment variables of the
zpodengine worker instead of a `.env` file.

To point the deployer at a zPodFactory API that is not at
`http://<zpodfactory_host setting>:8000`, set `ZPODFACTORY_BASE_URL` as a **real
environment variable** of the zpodengine worker. Setting it in `.env` has no effect: the
config script reads it to build the `-u` option it passes, and only the deployer
subprocess loads `.env`.

> [!NOTE]
> The API token ends up in the deployer command line, which `cmd_execute` echoes to the
> Prefect flow logs. Anyone who can read those logs can read the token. Pass
> `ZPODFACTORY_ACCESS_TOKEN` through the environment and drop the `-a` option from
> `zpod_component_add_vcfinstaller.py` if that matters for your setup.

### Set as global default configuration

You can configure this as a default config-script for all new zPods using the
`ff_default_config_scripts` setting:

In the `zpodcore` directory, run:
```bash
# Set default config-scripts (comma-separated)
just zcli setting create -n ff_default_config_scripts -v "vcfdeployer" -d ""
```

### Updating the deployer

The submodule tracks the deployer's `main` (`branch = main` in `.gitmodules`), and
`ignore = all` keeps the moved submodule out of `git status`, so there is nothing to commit
here when the deployer changes. To pull its latest `main`:

```bash
git pull
git submodule update --init --remote
```
