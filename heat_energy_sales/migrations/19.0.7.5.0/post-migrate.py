from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Shorten the old demo footer without touching a user's custom text."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    company = env.ref("heat_energy_sales.company_heat_demo", raise_if_not_found=False)
    legacy = {
        "Heat Energy Sales - monthly consumption and allocation",
        "Щомісячний розподіл теплової енергії. Відділ збуту постачальника.",
    }
    if company and company.heat_report_footer in legacy:
        company.heat_report_footer = "Щомісячний розподіл теплової енергії"
