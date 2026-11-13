from . import (
    account_move,
    consumer_category,
    heat_bill,
    heat_bill_line,
    meter,
    meter_reading,
    res_company,
    res_partner,
    supply_node,
    supply_object,
    tariff,
)

# Register the demo extension after its base model on fresh installations.
# isort: off
from . import demo_setup
# isort: on
