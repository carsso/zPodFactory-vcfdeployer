import os
import shlex
from pathlib import Path

from sqlmodel import select
from zpodcommon import models as M
from zpodcommon.enums import UserStatus, ZpodPermission, ZpodStatus
from zpodcommon.lib.dbutils import DBUtils
from zpodengine.lib import database
from zpodengine.lib.commands import cmd_execute

# zpod-vcf-deployer git submodule, sitting next to this config script
DEPLOYER_DIR = Path(__file__).resolve().parent / "zpod-vcf-deployer"
DEPLOYER_SCRIPT = "zpod-vcf-deployer.py"

# Custom VCF templates, taking precedence over the ones the deployer ships
CUSTOM_CONFIG_DIR = Path(__file__).resolve().parent / "config"

# Port the zPodFactory API listens on, used to build the base URL the deployer
# connects back to. Set the ZPODFACTORY_BASE_URL environment variable when the
# API lives somewhere else (a `.env` entry would not do: it is loaded by the
# deployer subprocess, way after we built the command line).
ZPODAPI_PORT = 8000


def execute_config_script(
    zpod_component_id: int,
) -> None:
    """
    Hand the freshly deployed VCF Installer over to zpod-vcf-deployer, which
    runs the whole VCF pipeline on it (DNS records, depot setup, bundle
    downloads, SDDC validation and SDDC deployment).

    The VCF JSON template is picked by zPod profile name, so a zPod deployed
    with the `v9.1.0.0_std_3hosts` profile uses `v9.1.0.0_std_3hosts.json`,
    from our own `config/` directory when it holds one, from the deployer's
    otherwise.

    Everything the deployer needs to talk back to zPodFactory (endpoint, API
    URL and access token) is read from this zPod and from the zPodFactory
    settings, so only the VCF depot settings are left to configure.

    Args:
        zpod_component_id: The zPod component ID
    """

    with database.get_session_ctx() as session:
        zpod_component = session.get(M.ZpodComponent, zpod_component_id)
        zpod = zpod_component.zpod

        deployer_options = {
            "-n": zpod.name,
            "-j": str(vcf_json_template(zpod.profile)),
            "-p": zpod.profile,
            "-e": zpod.endpoint.name,
            "-u": zpodfactory_base_url(),
            "-a": zpodfactory_access_token(session, zpod),
        }

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
                f"cd {shlex.quote(str(DEPLOYER_DIR))}"
                f" && uv run {DEPLOYER_SCRIPT}"
                + "".join(
                    f" {option} {shlex.quote(value)}"
                    for option, value in deployer_options.items()
                )
                + " --debug"
            )
            cmd_execute(cmd).check_returncode()
        finally:
            set_zpod_status(session, zpod, zpod_status)


def vcf_json_template(profile: str) -> Path:
    """
    Locate the VCF template for a zPod profile. A template dropped in our own
    `config/` directory wins over the deployer's, so a profile can be tweaked,
    or a new one added, without touching the submodule.
    """
    candidates = [
        CUSTOM_CONFIG_DIR / f"{profile}.json",
        DEPLOYER_DIR / "config" / f"{profile}.json",
    ]
    for candidate in candidates:
        if candidate.is_file():
            print(f"Using VCF template {candidate}")
            return candidate

    raise ValueError(
        f"No VCF template for zPod profile {profile}, looked for"
        f" {' and '.join(str(candidate) for candidate in candidates)}."
        " The zPod profile name must match a custom template or one of the"
        " deployer templates, see zpod-vcf-deployer/config/."
    )


def set_zpod_status(session, zpod, status) -> None:
    zpod.status = status
    session.add(zpod)
    session.commit()


def zpodfactory_base_url() -> str:
    """
    Build the zPodFactory API URL the deployer connects back to, from the
    zpodfactory_host setting. Flow containers share the zpodcore compose
    network, so that address is reachable from here.
    """
    if base_url := os.environ.get("ZPODFACTORY_BASE_URL"):
        return base_url

    zpodfactory_host = DBUtils.get_setting_value("zpodfactory_host")
    if not zpodfactory_host:
        raise ValueError(
            "Empty zpodfactory_host setting, cannot build the zPodFactory API"
            " URL for zpod-vcf-deployer. Set it, or set ZPODFACTORY_BASE_URL."
        )
    return f"http://{zpodfactory_host}:{ZPODAPI_PORT}"


def zpodfactory_access_token(session, zpod) -> str:
    """
    Pick the token the deployer authenticates with. It acts on this zPod, so
    use the zPod owner's token, and fall back to a superadmin when that
    account is disabled: the API only accepts tokens of ENABLED users.
    """
    for user in [
        user
        for permission in zpod.permissions
        if permission.permission == ZpodPermission.OWNER
        for user in permission.users
    ]:
        if user.status == UserStatus.ENABLED and user.api_token:
            return user.api_token

    superadmin = session.exec(
        select(M.User).where(
            M.User.superadmin.is_(True),
            M.User.status == UserStatus.ENABLED,
            M.User.api_token != "",
        )
    ).first()
    if superadmin:
        print(
            f"No usable owner for zPod {zpod.name}, falling back to superadmin"
            f" {superadmin.username} to run zpod-vcf-deployer"
        )
        return superadmin.api_token

    raise ValueError(
        f"No enabled user with an API token to run zpod-vcf-deployer against"
        f" zPod {zpod.name}."
    )
