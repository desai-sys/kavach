from tools.act import alert_family, record_verdict, start_golden_hour
from tools.investigate import (analyze_media, check_domain, check_reputation, inspect_link,
                               search_scam_playbooks)

ALL_TOOLS = [
    analyze_media,
    check_domain,
    inspect_link,
    check_reputation,
    search_scam_playbooks,
    alert_family,
    start_golden_hour,
    record_verdict,
]
