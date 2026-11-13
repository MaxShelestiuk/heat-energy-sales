Heat Energy Sales — Odoo 19
===========================

Course implementation of monthly heat metering, balanced allocation, guarded
approval, draft accounting invoices, private consumer portal and PDF reports.
All six implementation stages are available. Ukrainian translations and a
complete optional demonstration company are included.

Read heat_energy_sales/README.rst for installation, configuration, roles,
the calculation invariant, the mentor walkthrough and the twelve-requirement
map. Original requirements are in docs/COURSE_TECHNICAL_SPEC.md and
COURSE_MENTOR_OVERVIEW.html. Acceptance evidence is in docs/VALIDATION.md.

From this workspace's odoo_dev directory, validate on a disposable database::

    venv/bin/python odoo/odoo-bin --db_user=max-shelestiuk -d heat_acceptance --addons-path=odoo/addons,custom_addons/heat-energy-sales -i heat_energy_sales --with-demo --test-enable --test-tags=/heat_energy_sales --http-interface=127.0.0.1 --http-port=8082 --stop-after-init
    venv/bin/ruff check custom_addons/heat-energy-sales

Use --without-demo for a production-style empty installation and -u instead
of -i for an upgrade. The existing workspace server configuration is unchanged.
Enable Ukrainian through Odoo Settings / Translations / Languages, then select
it in user preferences. Demo portal login: heat.hospital.portal; set its password
explicitly in Settings before the demonstration.

License: LGPL-3.
