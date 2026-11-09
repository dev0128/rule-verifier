"""수집 보정 — RDS/Neptune 단독 인스턴스가 한 건도 점검되지 않던 문제 (위키 0107 "영향이 큰 것부터" 1행).

원인: 수집(Raw/Service/rds.py `_describe_db_clusters`)이 단독 인스턴스 항목에 `DBClusters = {}` 를 넣는다(2025-06-18 a600a819 부터).
룰은 `result_temp_i.get("DBClusters") == None` 일 때만 단독 인스턴스로 보고 점검한다 → 빈 dict 는 None 이 아니라 전부 건너뜀.

인스턴스 정보 자체는 raw 에 남아 있으므로 정보 손실이 아니다. 엔진에서는 수집 한 줄(빈 dict 를 넣지 않기)로 고친다 —
여기서는 이미 수집된 raw 에서 그 키를 지워 같은 효과를 낸다. RDS-001·005·006·009~015·018, NPT-001 이 다시 점검된다.
"""


def preprocess_raw(raw: dict) -> None:
    for region in raw.values():
        if not isinstance(region, dict):
            continue
        for service in ("rds", "neptune", "docdb"):
            for items in (region.get(service) or {}).values():  # describe_db_instances · describe_db_clusters …
                if not isinstance(items, list):
                    continue
                for item in items:
                    if isinstance(item, dict) and item.get("DBClusters") == {}:
                        del item["DBClusters"]
