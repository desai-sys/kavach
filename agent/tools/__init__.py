from tools.act import alert_family, record_verdict, start_golden_hour
from tools.business import business_action, check_business_records
from tools.everyday import cancel_appointment, find_appointment_slots, find_product_online, my_appointments
from tools.investigate import check_domain, check_reputation, inspect_link, search_scam_playbooks
from tools.settings import add_family_contact, open_settings

# analyze_media is not given to the model: evidence.build() reads every image/PDF once,
# before the model runs, and puts the findings in the evidence sheet.
ALL_TOOLS = [
    check_domain,
    inspect_link,
    check_reputation,
    search_scam_playbooks,
    check_business_records,
    business_action,
    find_product_online,
    find_appointment_slots,
    my_appointments,
    cancel_appointment,
    open_settings,
    add_family_contact,
    alert_family,
    start_golden_hour,
    record_verdict,
]
