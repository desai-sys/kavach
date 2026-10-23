from tools.act import alert_family, record_verdict, start_golden_hour
from tools.investigate import check_domain, check_reputation, inspect_link, search_scam_playbooks

# analyze_media is not given to the model: evidence.build() reads every image/PDF once,
# before the model runs, and puts the findings in the evidence sheet.
ALL_TOOLS = [
    check_domain,
    inspect_link,
    check_reputation,
    search_scam_playbooks,
    alert_family,
    start_golden_hour,
    record_verdict,
]
