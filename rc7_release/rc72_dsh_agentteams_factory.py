"""GAP-02 package-owned Mission factory with real DSH AgentTeams Host.

The bank supplies one approved local Host provider with a function named
create_captain_observation_provider, returning CaptainProviderWiring. It
must obtain membership from the installed DSH AgentTeams control-plane,
not JSON/model text. The package itself verifies local DSH session liveness
and creates or reenters an R1 Captain with existing signed Host contracts.
Without the trusted provider, this route fails closed.
"""
import importlib
import re
from dataclasses import dataclass
from typing import Mapping, Sequence

from rc7_runtime.models import ContractError
from rc7_runtime.rc72_authority import RC72AuthorityRuntime
from .rc72_dsh_agentteams_host import LocalDshAgentTeamsHost, SignedAgentTeamsCaptain
from .rc72_captain_host_reentry import ObservedDshCaptainStartup
from .rc72_configured_mission import configured_mission_bindings


@dataclass(frozen=True)
class CaptainProviderWiring:
    proof: SignedAgentTeamsCaptain
    membership_authority: RC72AuthorityRuntime
    host_authority: RC72AuthorityRuntime
    role_profiles: Mapping
    approved_capabilities: Sequence


def configured_agentteams_host_bindings(
    truth, *, release_id, source_commit, release_batch_id,
    config_path, provider_module, dsh_base_url,
):
    """Obtain authenticated membership and real session, then compose."""
    if (not isinstance(provider_module, str)
            or not re.fullmatch(r'[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*', provider_module)):
        raise ContractError('C07_DSH_HOST_PROVIDER_MODULE_REQUIRED')
    try:
        module = importlib.import_module(provider_module)
    except Exception as exc:
        raise ContractError('C07_DSH_HOST_PROVIDER_LOAD_FAILED:' +
                            type(exc).__name__) from None
    factory = getattr(module, 'create_captain_observation_provider', None)
    if not callable(factory):
        raise ContractError('C07_DSH_HOST_APPROVED_PROVIDER_FACTORY_REQUIRED')
    try:
        wiring = factory(truth=truth, release_id=release_id,
                         source_commit=source_commit,
                         release_batch_id=release_batch_id)
    except Exception as exc:
        raise ContractError('C07_DSH_HOST_PROVIDER_OBSERVATION_FAILED:' +
                            type(exc).__name__) from None
    if type(wiring) is not CaptainProviderWiring:
        raise ContractError('C07_DSH_HOST_TYPED_PROVIDER_REQUIRED')
    if (type(wiring.proof) is not SignedAgentTeamsCaptain
            or type(wiring.membership_authority) is not RC72AuthorityRuntime
            or type(wiring.host_authority) is not RC72AuthorityRuntime
            or not isinstance(wiring.role_profiles, Mapping)
            or not wiring.role_profiles
            or not isinstance(wiring.approved_capabilities,
                              (tuple, list, frozenset, set))
            or not wiring.approved_capabilities):
        raise ContractError('C07_DSH_HOST_TYPED_ROLE_AND_IDENTITY_REQUIRED')
    observer = LocalDshAgentTeamsHost(
        base_url=dsh_base_url,
        membership_authority=wiring.membership_authority,
        host_authority=wiring.host_authority)
    observation = observer.observe(
        truth=truth, release_id=release_id, source_commit=source_commit,
        release_batch_id=release_batch_id, proof=wiring.proof)
    options = dict(
        truth=truth, release_id=release_id, source_commit=source_commit,
        release_batch_id=release_batch_id, config_path=config_path,
        host_authority=wiring.host_authority,
        captain_role_profiles=wiring.role_profiles,
        captain_approved_capabilities=wiring.approved_capabilities)
    if isinstance(observation, ObservedDshCaptainStartup):
        options['observed_captain_startup'] = observation
    else:
        options['observed_captain'] = observation
    return configured_mission_bindings(**options)
