import json
import logging
from typing import Optional, Dict, Any, List, Tuple, Union
from urllib.parse import urlparse

import webauthn
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url
from webauthn.helpers.cose import COSEAlgorithmIdentifier
from webauthn.helpers.structs import (
    AttestationConveyancePreference,
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

import database

logger = logging.getLogger(__name__)


def extract_rp_id(host: str) -> str:
    """
    Extracts the clean Relying Party ID (domain name) from request host header,
    stripping ports and handling IPv4/IPv6/localhost appropriately.
    """
    if not host:
        return "localhost"
    # Remove port if present
    h = host.split(":")[0].strip().lower()
    return h or "localhost"


def get_allowed_origins(request) -> List[str]:
    """
    Constructs acceptable WebAuthn origins for the incoming request,
    including both http and https schemes and localhost/127.0.0.1 aliases.
    """
    scheme = request.headers.get("X-Forwarded-Proto") or request.scheme or "http"
    host = request.host

    origins = {
        f"{scheme}://{host}",
        f"http://{host}",
        f"https://{host}",
    }

    # If accessing via localhost or 127.0.0.1, allow the sibling loopback variant
    if "localhost" in host:
        sibling = host.replace("localhost", "127.0.0.1")
        origins.add(f"http://{sibling}")
        origins.add(f"https://{sibling}")
    elif "127.0.0.1" in host:
        sibling = host.replace("127.0.0.1", "localhost")
        origins.add(f"http://{sibling}")
        origins.add(f"https://{sibling}")

    return list(origins)


def generate_registration_options(
    user_id_str: str,
    username: str,
    display_name: str,
    rp_id: str
) -> Dict[str, Any]:
    """
    Generates WebAuthn registration options for creating a new passkey / biometric credential.
    """
    user_id_bytes = user_id_str.encode("utf-8")
    
    # Exclude already registered credentials for this user to avoid duplicates
    existing_creds = database.list_webauthn_credentials(user_id_str)
    exclude_list = []
    for c in existing_creds:
        try:
            exclude_list.append(
                PublicKeyCredentialDescriptor(
                    id=base64url_to_bytes(c["credential_id"])
                )
            )
        except Exception:
            pass

    options = webauthn.generate_registration_options(
        rp_id=rp_id,
        rp_name="GlycoGuide Remastered",
        user_id=user_id_bytes,
        user_name=username,
        user_display_name=display_name or username,
        attestation=AttestationConveyancePreference.NONE,
        authenticator_selection=AuthenticatorSelectionCriteria(
            authenticator_attachment=None,  # Supports platform (Touch ID/Face ID/Windows Hello) + security keys
            user_verification=UserVerificationRequirement.PREFERRED,
            resident_key=ResidentKeyRequirement.PREFERRED,
        ),
        exclude_credentials=exclude_list if exclude_list else None,
        supported_pub_key_algs=[
            COSEAlgorithmIdentifier.ECDSA_SHA_256,
            COSEAlgorithmIdentifier.RSASSA_PKCS1_v1_5_SHA_256,
            COSEAlgorithmIdentifier.EDDSA,
        ],
        timeout=60000,
    )

    # Save challenge to database for validation
    challenge_b64 = bytes_to_base64url(options.challenge)
    database.save_webauthn_challenge(challenge_b64, "register", user_id_str)

    return json.loads(webauthn.options_to_json(options))


def verify_registration(
    credential_data: Union[str, Dict[str, Any]],
    rp_id: str,
    allowed_origins: List[str],
    device_name: str = "Biometric Device",
    user_id_str: str = "family-shared-device"
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """
    Verifies the client's credential creation response and saves the verified credential.
    """
    try:
        # Extract clientDataJSON to get the challenge
        if isinstance(credential_data, str):
            cred_dict = json.loads(credential_data)
        else:
            cred_dict = credential_data

        client_data_raw = cred_dict.get("response", {}).get("clientDataJSON")
        if not client_data_raw:
            return False, "Missing clientDataJSON in registration response.", None

        # Decode clientDataJSON to inspect challenge
        client_data_bytes = base64url_to_bytes(client_data_raw)
        client_data = json.loads(client_data_bytes.decode("utf-8"))
        challenge_b64 = client_data.get("challenge")

        if not challenge_b64:
            return False, "Missing challenge in clientDataJSON.", None

        # Validate and consume stored challenge
        stored_challenge = database.consume_webauthn_challenge(challenge_b64, "register")
        if not stored_challenge:
            return False, "Invalid or expired registration challenge. Please try again.", None

        # Verify registration response with WebAuthn library
        verified = webauthn.verify_registration_response(
            credential=cred_dict,
            expected_challenge=base64url_to_bytes(challenge_b64),
            expected_rp_id=rp_id,
            expected_origin=allowed_origins,
            require_user_verification=False,
        )

        credential_id_b64 = bytes_to_base64url(verified.credential_id)
        transports = ",".join(cred_dict.get("response", {}).get("transports") or [])

        # Save to database
        saved_cred = database.save_webauthn_credential(
            user_id=user_id_str,
            credential_id=credential_id_b64,
            public_key=verified.credential_public_key,
            sign_count=verified.sign_count,
            transports=transports,
            device_name=device_name,
        )

        return True, "Biometric passkey registered successfully.", saved_cred

    except Exception as e:
        logger.warning(f"Registration verification failed: {e}")
        return False, f"Verification failed: {str(e)}", None


def generate_authentication_options(
    rp_id: str,
    user_id_str: str = "family-shared-device"
) -> Dict[str, Any]:
    """
    Generates WebAuthn authentication options with allowed credentials for the user.
    """
    creds = database.list_webauthn_credentials(user_id_str)
    allow_credentials = []
    for c in creds:
        try:
            allow_credentials.append(
                PublicKeyCredentialDescriptor(
                    id=base64url_to_bytes(c["credential_id"])
                )
            )
        except Exception:
            pass

    options = webauthn.generate_authentication_options(
        rp_id=rp_id,
        allow_credentials=allow_credentials if allow_credentials else None,
        user_verification=UserVerificationRequirement.PREFERRED,
        timeout=60000,
    )

    challenge_b64 = bytes_to_base64url(options.challenge)
    database.save_webauthn_challenge(challenge_b64, "login", user_id_str)

    return json.loads(webauthn.options_to_json(options))


def verify_authentication(
    credential_data: Union[str, Dict[str, Any]],
    rp_id: str,
    allowed_origins: List[str]
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """
    Verifies the client's authentication assertion and updates sign count.
    """
    try:
        if isinstance(credential_data, str):
            cred_dict = json.loads(credential_data)
        else:
            cred_dict = credential_data

        credential_id_b64 = cred_dict.get("id")
        if not credential_id_b64:
            return False, "Missing credential ID in authentication response.", None

        # Look up saved credential
        saved_cred = database.get_webauthn_credential_by_id(credential_id_b64)
        if not saved_cred:
            return False, "Unrecognized biometric credential on this server.", None

        # Extract clientDataJSON to get the challenge
        client_data_raw = cred_dict.get("response", {}).get("clientDataJSON")
        if not client_data_raw:
            return False, "Missing clientDataJSON in authentication response.", None

        client_data_bytes = base64url_to_bytes(client_data_raw)
        client_data = json.loads(client_data_bytes.decode("utf-8"))
        challenge_b64 = client_data.get("challenge")

        if not challenge_b64:
            return False, "Missing challenge in clientDataJSON.", None

        # Validate and consume stored challenge
        stored_challenge = database.consume_webauthn_challenge(challenge_b64, "login")
        if not stored_challenge:
            return False, "Invalid or expired authentication challenge. Please try again.", None

        # Verify authentication response with WebAuthn library
        verified = webauthn.verify_authentication_response(
            credential=cred_dict,
            expected_challenge=base64url_to_bytes(challenge_b64),
            expected_rp_id=rp_id,
            expected_origin=allowed_origins,
            credential_public_key=saved_cred["public_key"],
            credential_current_sign_count=saved_cred["sign_count"],
            require_user_verification=False,
        )

        # Update usage timestamp and new sign count
        database.update_webauthn_credential_usage(
            credential_id_b64,
            verified.new_sign_count
        )

        return True, "Biometric authentication successful.", saved_cred

    except Exception as e:
        logger.warning(f"Authentication verification failed: {e}")
        return False, f"Biometric verification failed: {str(e)}", None
