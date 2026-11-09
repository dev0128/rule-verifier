"""findings.json 을 처음 만든 스크립트 (2026-11-09, 한 번 실행).

원천
- 위키 0107-spike/all_findings.json — 2026-10-06 전수 점검 150건 (F001~F150, 파일 순서 그대로)
- 위키 0107 본문 "인자 없을 때 예외" 8건, 0106 운영 예외 5건, 2026-10-13 동작 기록 · 2026-10-07/12 고객 데이터 대조에서 나온 것 (X001~)

이후로는 findings.json 을 직접 고친다(이 스크립트를 다시 돌리면 손으로 고친 것이 사라진다).

    python catalog/build_catalog.py <wiki>/00-common/0107-spike/all_findings.json
"""

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
META = json.loads((HERE / "rule_meta.json").read_text(encoding="utf-8"))
BY_CODE = {v["code"]: k for k, v in META.items()}


def effect_of(impact: str, typ: str, summary: str) -> str:
    t = f"{impact} {summary}"
    if typ in ("crash", "args"):
        return "crash"
    if "오탐" in t or "항상 취약" in t or "무조건 취약" in t or "취약으로" in t or "취약 처리" in t:
        return "false_positive"
    if "놓침" in t or "미탐" in t or "항상 양호" in t or "양호로" in t or "양호 처리" in t:
        return "false_negative"
    if "N/A" in t or "일부만" in t or "점검 안" in t or "빠짐" in t or "누락" in t:
        return "not_checked"
    return "wrong_logic"


# (codes, type, summary, impact, source, effect) — codes 의 첫 번째가 대표 룰
EXTRAS = [
    # 0106 — 운영 Loki 에서 실제로 예외가 난 룰 5개
    (["EC2-004"], "crash", "스냅샷 속성(CreateVolumePermissions) 조회 실패로 키가 없으면 TypeError — 수집도 그 뒤 스냅샷을 멈춤", "룰 전체 N/A(운영 예외 실측)", "0106", "crash"),
    (["VPC-007"], "crash", "엔드포인트 서비스 AllowedPrincipals 의 Principal 이 '*'(전체 허용)이면 split(':')[4] IndexError — 가장 위험한 설정에서 룰이 죽음", "룰 전체 N/A(운영 예외 실측, samsungcard 거버넌스 진단마다)", "0106", "crash"),
    (["DLM-001"], "crash", "태그 없는 EBS 볼륨 + 기본 정책 ExcludeTags → KeyError 'Tags' (TargetTags 경로 dlm.py:84 도 같음)", "룰 전체 N/A(운영 예외 실측)", "0106", "crash"),
    (["CFN-005"], "crash", "스택 역할 인라인 정책 Statement 가 NotAction 이면 KeyError 'Action'", "룰 전체 N/A(운영 예외 실측)", "0106", "crash"),
    (["CFN-001"], "logic", "리소스가 아니라 템플릿 최상위 키(Resources, AWSTemplateFormatVersion …)를 돌며 DeletionPolicy 를 찾음 → 모든 템플릿 취약. PyYAML 이 못 읽는 템플릿은 예외", "오탐(항상 취약) + 일부 템플릿 예외", "0106", "false_positive"),
    # 0107 — 인자 없을 때 예외 (거버넌스 기본 룰은 "", 커스텀룰 마스터 참조는 None)
    *[([c], "args", "인자가 None / \"\" / [] 로 오면 예외 — 거버넌스 기본 룰 · 커스텀룰 마스터 참조에서 항상 실패", "거버넌스 · 커스텀룰에서 룰 전체 N/A", "0107-args", "crash")
      for c in ("IAM-001", "IAM-005", "IAM-006", "IAM-007", "IAM-009", "IAM-019", "R53-005", "CWH-016")],
    # 0107 2026-10-13 — 마스터룰 동작 기록 중 새로 나온 것 (코드 읽기 · 일부만 실행 재현)
    (["SSM-003"], "logic", "세션을 Status == 'Active' 로 셈 — 세션 Status 값에 Active 는 없음(조회 필터 State 값)", "항상 0건 — 판정 고정", "0107-2026-10-13", "false_negative"),
    (["RDS-015"], "logic", "인스턴스 필드 EnhancedMonitoringResourceArn 을 클러스터에서 찾음 → Aurora 클러스터 전부 취약(MonitoringInterval 60 인 것 포함)", "오탐(Aurora 클러스터 전부 취약)", "0107-2026-10-13", "false_positive"),
    (["RDS-018"], "logic", "클러스터 경로가 \"\"\" 문자열 안에 막혀 있고 인스턴스 경로는 DBClusters={} 결함에 막힘", "항상 N/A (BackupRetentionPeriod 0 미탐)", "0107-2026-10-13", "not_checked"),
    (["API-006"], "logic", "v2 스테이지 AccessLogSettings 를 accessLogSettings(소문자)로 읽음", "오탐(v2 API 전부 취약)", "0107-2026-10-13", "false_positive"),
    (["API-007"], "logic", "CORS 프리플라이트 OPTIONS(authorizationType NONE)를 빼지 않음", "오탐(CORS 켠 REST API 거의 전부 취약)", "0107-2026-10-13", "false_positive"),
    (["ECS-002"], "logic", "판단기준은 메모리/CPU 제한인데 ulimits 만 봄", "오탐(대부분 컨테이너 취약)", "0107-2026-10-13", "false_positive"),
    (["EC2-012"], "logic", "UseVolume 분기가 효과 없음 — 기본 암호화 꺼진 리전은 볼륨이 없어도 취약", "오탐", "0107-2026-10-13", "false_positive"),
    (["EKS-008"], "logic", "AWS 문서 파싱 실패 시 전부 양호 · 최신 버전만 양호", "미탐(문서 조회 실패 시) / 오탐(최신이 아닌 지원 버전)", "0107-2026-10-13", "wrong_logic"),
    (["RDS-012", "NPT-001"], "logic", "명시적 연결 없이 메인 라우팅 테이블을 쓰는 서브넷은 매칭 안 됨", "미탐(항상 양호)", "0107-2026-10-13", "false_negative"),
    (["IAM-005"], "logic", "key_value 를 사용자 루프 안에서 덮어쓰고 되돌리지 않음 — 두 번째 사용자부터 판정 대상이 바뀜", "같은 자격 증명 두 사용자가 양호 · 취약으로 갈림", "0107-2026-10-13", "wrong_logic"),
    (["IAM-016", "IAM-018"], "logic", "신뢰 정책에 Service 주체가 하나라도 있으면 역할을 뺌 — AWS 주체가 섞인 역할도 점검 안 함", "미탐", "0107-2026-10-13", "false_negative"),
    (["SNS-005", "LAM-006"], "logic", "Effect 를 보지 않아 Deny 문도 취약", "오탐", "0107-2026-10-13", "false_positive"),
    (["ECS-004"], "logic", "\"root\" in user 부분 일치 — nonroot 사용자도 취약", "오탐", "0107-2026-10-13", "false_positive"),
    (["EKS-006"], "logic", "IPv6(::/0) 미검사", "미탐", "0107-2026-10-13", "false_negative"),
    (["EKS-003"], "logic", "VPC · FlowLogs 정보가 없으면 양호", "미탐", "0107-2026-10-13", "false_negative"),
    (["CWH-001"], "logic", "CWH-001~014: 필터 패턴 문자열 비교 — 따옴표 표기만 달라도 미탐, 같은 필터의 마지막 알람/트레일 매치가 결과를 덮음", "미탐", "0107-2026-10-13", "false_negative"),
    (["CWH-018"], "logic", "계정의 모든 역할이 양호 행으로 나옴", "판정 무의미(양호 행 과다)", "0107-2026-10-13", "wrong_logic"),
    (["CLT-004", "CLT-006"], "logic", "파티션 판정이 cn-north-1 · us-gov-east-1 만 — cn-northwest-1 · us-gov-west-1 클래식 셀렉터는 항상 취약. 고급 셀렉터는 버킷 일부만 로깅해도 양호", "오탐 + 미탐", "0107-2026-10-13", "wrong_logic"),
    (["CLT-005"], "logic", "응답 객체 자체가 비었는지만 봄", "판정 무의미", "0107-2026-10-13", "wrong_logic"),
    (["CDN-002"], "logic", "버킷 정책을 문자열 완전 일치로 봄 — 리스트 Action · s3:Get* · ArnLike · Principal 리스트면 오탐. 점이 든 버킷명을 못 찾음(CDN-010 도)", "오탐", "0107-2026-10-13", "false_positive"),
    (["CDN-009"], "logic", "원본 순서에 따라 결과가 달라짐", "판정 불안정", "0107-2026-10-13", "wrong_logic"),
    (["DLM-001"], "logic", "ExcludeVolumeTypes · ExcludeBootVolumes 조건 반전(제외가 안 됨) · 정책 여러 개면 서로의 대상을 취약으로 · 마지막 TargetTags 키만 · 유효 정책 없으면 전부 양호", "오탐 + 미탐", "0107-2026-10-13", "wrong_logic"),
    (["EBT-003"], "logic", "판단기준은 S3 게시 또는 CloudWatch 인데 둘 다 요구", "오탐", "0107-2026-10-13", "false_positive"),
    (["EBT-002"], "logic", "HealthStatus 없으면 양호", "미탐", "0107-2026-10-13", "false_negative"),
    (["AMH-002"], "logic", "가상 게이트웨이가 없으면 취약 (AMH-001 · 003 · 004 는 양호)", "오탐", "0107-2026-10-13", "false_positive"),
    (["RDS-003"], "logic", "OEM 옵션을 찾으면 그룹의 모든 옵션 포트를 봄(포트 없는 옵션 하나로 양호) · *-cdb 오라클은 전부 N/A", "미탐 + 점검 누락", "0107-2026-10-13", "false_negative"),
    (["GDT-002"], "logic", "GDT-002~007: 응답에 없는 기능은 양호, GDT-002 · 005 는 DataSources 만 봄", "미탐", "0107-2026-10-13", "false_negative"),
    (["CFG-002"], "logic", "첫 번째 레코더만 봄", "일부만 점검", "0107-2026-10-13", "not_checked"),
    (["ATN-001"], "logic", "EnforceWorkGroupConfiguration 을 보지 않음", "미탐(클라이언트가 설정을 덮을 수 있는 작업그룹)", "0107-2026-10-13", "false_negative"),
    (["ECS-011"], "logic", "최신 에이전트 버전을 프로세스 환경변수에 캐시하고 갱신하지 않음 · 정확히 일치해야 양호", "오탐(최신이 바뀐 뒤)", "0107-2026-10-13", "false_positive"),
    (["EC2-012", "ELB-003", "ELB-011", "SMK-001"], "collection", "수집 실패가 판정으로 둔갑 — 조회 실패로 빈 {} 행이 들어가면 취약", "오탐(수집 실패 = 취약)", "0107-2026-10-13", "false_positive"),
    (["EC2-002", "ELB-004"], "collection", "수집 실패가 판정으로 둔갑 — 조회 실패로 값이 비면 양호 (ELB-004~006)", "미탐(수집 실패 = 양호)", "0107-2026-10-13", "false_negative"),
    (["AMH-001"], "collection", "AppMesh 수집 _describe_virtual_gateway 가 루프 안에서 method_key 를 덮어써 메시 2개 이상인 리전은 AMH 4개 모두 KeyError", "룰 전체 N/A", "0107-2026-10-13", "crash"),
    (["CLT-002", "SSM-004", "EC2-007", "VPC-004", "VPC-007", "IAM-016", "AAN-001"], "crash", "리전에 서비스 키가 없을 때 가드 없음(AAN-001 은 globals.account) — 한 리전 수집이 비면 KeyError", "룰 전체 N/A", "0107-2026-10-13", "crash"),
    (["VPC-009"], "crash", "describe_firewall 실패 시 [] → TypeError", "룰 전체 N/A", "0107-2026-10-13", "crash"),
    (["SES-002"], "crash", "Principal 없는 정책 문에서 예외 · SES 수집 실패 시 루프 중단", "룰 전체 N/A", "0107-2026-10-13", "crash"),
    (["AMQ-002"], "crash", "describe 실패로 {} 행이 들어가면 예외", "룰 전체 N/A", "0107-2026-10-13", "crash"),
    (["SSM-005"], "crash", "문서 권한 조회 실패로 {} 가 들어가면 예외", "룰 전체 N/A", "0107-2026-10-13", "crash"),
    (["ACM-002"], "crash", "ACM-001~004: describe_certificate 실패로 Certificate: None 이면 예외", "룰 전체 N/A", "0107-2026-10-13", "crash"),
    (["IAM-017"], "crash", "Users 키가 없는 그룹에서 예외", "룰 전체 N/A", "0107-2026-10-13", "crash"),
    (["ASG-004"], "crash", "UserData base64 디코드 예외 처리 없음", "룰 전체 N/A", "0107-2026-10-13", "crash"),
    (["DOC-002"], "crash", "기본값 파라미터에 ParameterValue 가 없으면 예외 (미확인)", "룰 전체 N/A", "0107-2026-10-13", "crash"),
    # 0107 2026-10-07 / 10-12 — 고객 데이터(삼성카드 15개 계정) 대조
    (["S3-002", "S3-013", "S3-014", "S3-016"], "collection", "S3 수집이 버킷 단위 API 실패 시 Grants=[] · 암호화 {} · 퍼블릭 차단 4종 false · Policy={} 를 채움 — 실패가 '보안 미설정'으로 위장", "오탐(고객 34개 버킷)", "0107-customer", "false_positive"),
    (["S3-011"], "logic", "ACL 만 보고 버킷 정책을 보지 않음 — 정책으로 공개된 버킷 미탐 (수집 실패 시 기본값으로 공개 탐지도 놓침)", "미탐", "0107-customer", "false_negative"),
    (["ECR-004"], "collection", "이미지 563개 전부 find_scan=false(스캔 COMPLETE 394개 포함) — 심각도 건수 전부 0 (원인 미확정)", "미탐 의심(전건 양호)", "0107-customer", "false_negative"),
    (["ECS-009"], "logic", "pidMode 를 컨테이너 정의 안에서 찾음 — AWS 정의상 태스크 정의 최상위", "미탐(항상 양호)", "0107-customer", "false_negative"),
    (["S3-016"], "logic", "퍼블릭 액세스 차단 4종 중 2종만 보고 계정 수준 설정 무시", "판정 범위 축소", "0107-customer", "wrong_logic"),
    (["CDN-003"], "logic", "기본 캐시 동작만 봄 — 추가 동작의 HTTP 허용 미탐", "미탐", "0107-customer", "false_negative"),
    (["SMK-001"], "logic", "노트북 서브넷의 NAT 경로를 보지 않음", "미탐(고객 노트북 2건)", "0107-customer", "false_negative"),
    (["LAM-010"], "logic", "사용자 지정 런타임 목록에 provided.al2 / provided.al2023 미포함", "미탐", "0107-customer", "false_negative"),
    (["TAD-001"], "logic", "Red/Yellow 결과를 보던 원래 함수는 문자열로 막혀 있고, 지금 함수는 TA 체크 목록이 조회되는지만 봄", "판정 무의미(오류 · 경고 검토 여부 미판정)", "0107-customer", "wrong_logic"),
]


def main(all_findings_path: str) -> None:
    src = json.loads(Path(all_findings_path).read_text(encoding="utf-8"))
    out = []
    for i, f in enumerate(src, 1):
        out.append(
            {
                "id": f"F{i:03d}",
                "rule": f["rule"],
                "code": f["code"],
                "codes": [f["code"]],
                "name": f.get("name", ""),
                "level": f.get("level", ""),
                "type": f["type"],
                "effect": effect_of(f.get("impact", ""), f["type"], f.get("summary", "")),
                "summary": f.get("summary", ""),
                "trigger": f.get("trigger", ""),
                "evidence": f.get("evidence", ""),
                "impact": f.get("impact", ""),
                "confidence": f.get("confidence", ""),
                "reproduced_in_spike": f.get("reproduced", ""),
                "source": "0107-spike",
            }
        )
    for j, (codes, typ, summary, impact, source, effect) in enumerate(EXTRAS, 1):
        full = [f"AWS-{c}" for c in codes]
        rule = BY_CODE[full[0]]
        m = META[rule]
        out.append(
            {
                "id": f"X{j:03d}",
                "rule": rule,
                "code": full[0],
                "codes": full,
                "name": m["name"],
                "level": m["report_lv"],
                "type": typ,
                "effect": effect,
                "summary": summary,
                "trigger": "",
                "evidence": "",
                "impact": impact,
                "confidence": "high" if source in ("0106", "0107-args") else "medium",
                "reproduced_in_spike": "yes (0106 spike_rules.py)" if source == "0106" else "",
                "source": source,
            }
        )
    (HERE / "findings.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(len(out), "findings")


if __name__ == "__main__":
    main(sys.argv[1])
