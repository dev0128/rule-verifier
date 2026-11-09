"""잘못된 필드 · 값을 보던 룰 — 고친 판정식만 바꾼 개선안 (예시).

엔진의 원 함수를 복사해 판정 부분만 고쳤다. 이름(REME_…)이 같으면 원 함수를 덮어쓴다.
엔진에 반영할 때는 이 차이만 옮기면 된다.
"""

from datetime import datetime, timezone

from AWS.Analyze.Service.acm import *  # noqa: F401,F403 — AWS_keybase, result_items_ 등 원 모듈과 같은 이름공간
from ANALYZE_CORE.Util.ResultOrganizer import result_items_  # noqa: F811
from ANALYZE_CORE.Util.keyword_base import AWS_keybase  # noqa: F811

FIXES = {
    "REME_0101100001": "ACM-001 — 존재하지 않는 DomainValidationOptions[].ValidationStatus=='EXPIRED' 대신 Certificate.Status=='EXPIRED' 또는 NotAfter 경과로 판정 (F075)",
    "REME_0103900007": "R53-007 — R53-006 을 복사한 채 TransferLock 을 보던 것을 AutoRenew 로 (F011)",
    "REME_0100700003": "S3-003 — MFADelete 가 None 일 때만 취약 → 'Enabled' 가 아니면 취약 (F078)",
    "REME_0100700004": "S3-004 — Status 가 None 일 때만 취약 → 'Enabled' 가 아니면 취약(Suspended 포함) (F077)",
    "REME_0106000003": "ECR-003 — imageScanningConfiguration 에서 'imageScanningConfiguration' 을 다시 찾던 것을 scanOnPush 로 (F144)",
}


def _expired(cert: dict) -> bool:
    if cert.get("Status") == "EXPIRED":
        return True
    na = cert.get("NotAfter")
    if not na:
        return False
    try:
        t = na if isinstance(na, datetime) else datetime.fromisoformat(str(na).replace("Z", "+00:00"))
    except ValueError:
        return False
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return t < datetime.now(timezone.utc)


def REME_0101100001(result, args_, json_given, service_name):
    key_value, check_value = ["Certificate", "Status"], ["NotAfter"]
    regions_list = [key for key in json_given["raw"].keys() if key != "globals"]
    for region in regions_list:
        if not json_given["raw"][region].get(service_name):
            continue
        for result_temp_i in json_given["raw"][region][service_name]["list_certificates"]:
            _select_value = list(result_temp_i.keys())
            dclo_alnayze_id = AWS_keybase[service_name]["list_certificates"]["id"]
            result_temp_i.update({"dclo_alnayze_id": f"Certificate||{dclo_alnayze_id}"})
            result_temp_i.update({"dclo_alnayze_region": f"{region}"})
            result["checked_items"] += 1
            cert = result_temp_i.get(key_value[0]) or result_temp_i
            key_data = {"Status": cert.get("Status", result_temp_i.get("Status")), "NotAfter": str(cert.get("NotAfter", result_temp_i.get("NotAfter", "")))}
            flag = _expired({**result_temp_i, **cert})
            result_items_(result, service_name, result_temp_i, key_value, _select_value, flag, connected_=None, connected_service=None, key_data=key_data)
    result["check_value"] = ["Certificate.Status", "Certificate.NotAfter"]
    return result


def REME_0103900007(result, args_, json_given, service_name):
    key_value = ["AutoRenew"]
    for region in [key for key in json_given["raw"].keys() if key == "globals"]:
        if not json_given["raw"][region].get(service_name):
            continue
        for result_temp_i in json_given["raw"][region][service_name]["get_domain_detail"]:
            _select_value = list(result_temp_i.keys())
            dclo_alnayze_id = AWS_keybase[service_name]["get_domain_detail"]["id"]
            result_temp_i.update({"dclo_alnayze_id": f"Domains||{dclo_alnayze_id}"})
            result_temp_i.update({"dclo_alnayze_region": f"{region}"})
            result["checked_items"] += 1
            key_data = {key_value[0]: result_temp_i.get(key_value[0])}
            flag = key_data[key_value[0]] not in (True, "True", "true")
            result_items_(result, service_name, result_temp_i, key_value, _select_value, flag, connected_=None, connected_service=None, key_data=key_data)
    result["check_value"] = ["AutoRenew"]
    return result


def _s3_versioning_rule(result, json_given, service_name, field):
    key_value = ["bucket_versioning"]
    for region in [key for key in json_given["raw"].keys() if key == "globals"]:
        if not json_given["raw"][region].get(service_name):
            continue
        for result_temp_i in json_given["raw"][region][service_name]["list_buckets"]:
            _select_value = list(result_temp_i.keys())
            dclo_alnayze_id = AWS_keybase[service_name]["list_buckets"]["id"]
            result_temp_i.update({"dclo_alnayze_id": f"Bucket||{dclo_alnayze_id}"})
            result_temp_i.update({"dclo_alnayze_region": f"{region}"})
            result["checked_items"] += 1
            key_data = result_temp_i.get(key_value[0]) or {}
            flag = key_data.get(field) != "Enabled"
            result_items_(result, service_name, result_temp_i, key_value, _select_value, flag, connected_=None, connected_service=None, key_data=key_data)
    result["check_value"] = [f"bucket_versioning.{field}"]
    return result


def REME_0100700003(result, args_, json_given, service_name):
    return _s3_versioning_rule(result, json_given, service_name, "MFADelete")


def REME_0100700004(result, args_, json_given, service_name):
    return _s3_versioning_rule(result, json_given, service_name, "Status")


def REME_0106000003(result, args_, json_given, service_name):
    key_value = ["imageScanningConfiguration"]
    for region in [key for key in json_given["raw"].keys() if key != "globals"]:
        if not json_given["raw"][region].get(service_name):
            continue
        for result_temp_i in json_given["raw"][region][service_name]["describe_repositories"]:
            _select_value = list(result_temp_i.keys())
            dclo_alnayze_id = AWS_keybase[service_name]["describe_repositories"]["id"]
            result_temp_i.update({"dclo_alnayze_id": f"Repositorie||{dclo_alnayze_id}"})
            result_temp_i.update({"dclo_alnayze_region": f"{region}"})
            result["checked_items"] += 1
            key_data = result_temp_i.get(key_value[0]) or {}
            flag = key_data.get("scanOnPush") is not True
            result_items_(result, service_name, result_temp_i, key_value, _select_value, flag, connected_=None, connected_service=None, key_data=key_data)
    result["check_value"] = ["imageScanningConfiguration.scanOnPush"]
    return result
