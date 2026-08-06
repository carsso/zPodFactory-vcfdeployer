import os
from pathlib import Path

from zpodcommon import models as M
from zpodcommon.enums import ZpodStatus
from zpodengine.lib import database
from zpodengine.lib.commands import cmd_execute

# zpod-vcf-deployer git submodule, sitting next to this config script
DEPLOYER_DIR = Path(__file__).resolve().parent / "zpod-vcf-deployer"
DEPLOYER_SCRIPT = "zpod-vcf-deployer.py"

# Settings the deployer needs but that the command line below does not carry.
# They come from the environment, or from the `.env` file the deployer loads
# itself through python-dotenv.
REQUIRED_SETTINGS = (
    "ZPODFACTORY_BASE_URL",
    "ZPODFACTORY_ACCESS_TOKEN",
    "ZPODFACTORY_DEFAULT_ENDPOINT",
    "ZPODFACTORY_DEFAULT_PROFILE",
)


def execute_config_script(
    zpod_component_id: int,
) -> None:
    """
    Hand the freshly deployed VCF Installer over to zpod-vcf-deployer, which
    runs the whole VCF pipeline on it (DNS records, depot setup, bundle
    downloads, SDDC validation and SDDC deployment).

    The VCF JSON template is picked from the deployer's `config/` directory
    using the zPod profile name, so a zPod deployed with the
    `v9.1.0.0_std_3hosts` profile uses `config/v9.1.0.0_std_3hosts.json`.

    Args:
        zpod_component_id: The zPod component ID
    """

    with database.get_session_ctx() as session:
        zpod_component = session.get(M.ZpodComponent, zpod_component_id)
        zpod = zpod_component.zpod

        vcf_json_template = f"config/{zpod.profile}.json"
        if not (DEPLOYER_DIR / vcf_json_template).is_file():
            raise ValueError(
                f"No VCF template {vcf_json_template} in {DEPLOYER_DIR}."
                " The zPod profile name must match one of the deployer"
                " templates, see zpod-vcf-deployer/config/."
            )

        check_deployer_settings()

        # The deployer looks the zPod up through the zPodFactory API and only
        # creates it when it is not ACTIVE yet. We run from the component add
        # flow, while the zPod is still BUILDING, so without this it would
        # deploy a second zPod under the same name. Everything the deployer
        # needs is up by now, so flag the zPod ACTIVE while it works, and put
        # the original status back afterwards to let the deploy flow finish
        # (and mark the zPod DEPLOY_FAILED should the VCF deployment fail).
        zpod_status = zpod.status
        set_zpod_status(session, zpod, ZpodStatus.ACTIVE)
        try:
            cmd = (
                f"cd {DEPLOYER_DIR}"
                f" && uv run {DEPLOYER_SCRIPT}"
                f" -n {zpod.name}"
                f" -j {vcf_json_template}"
                " --debug"
            )
            cmd_execute(cmd).check_returncode()
        finally:
            set_zpod_status(session, zpod, zpod_status)


def set_zpod_status(session, zpod, status) -> None:
    zpod.status = status
    session.add(zpod)
    session.commit()


def check_deployer_settings() -> None:
    """
    Fail before spawning the deployer when it has no way to know which
    zPodFactory instance and which depot to talk to.
    """
    missing = [
        setting
        for setting in REQUIRED_SETTINGS
        if setting not in os.environ and setting not in dotenv_settings()
    ]
    if missing:
        raise ValueError(
            f"Missing zpod-vcf-deployer settings: {', '.join(missing)}."
            f" Set them in the environment or in a .env file, see"
            f" {Path(__file__).resolve().parent / 'env_example.txt'}."
        )


def dotenv_settings() -> dict[str, str]:
    """
    Read the `.env` file the deployer will load. python-dotenv walks up from
    the deployer script and stops on the first `.env` it finds, so look for it
    in the submodule first, then next to this config script.
    """
    for env_file in (DEPLOYER_DIR / ".env", Path(__file__).resolve().parent / ".env"):
        if not env_file.is_file():
            continue
        settings = {}
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            settings[key.strip()] = value.strip()
        return settings
    return {}
