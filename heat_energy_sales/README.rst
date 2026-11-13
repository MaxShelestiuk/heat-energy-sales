Heat Energy Sales
=================

Українська
----------

Модуль рахує щомісячне споживання тепла, розподіляє його між об'єктами,
створює нарахування та чернетку рахунка Odoo. Користувач "Контролер" вносить показники лічильника, користувач "Збут" готує і виставляє нарахування, адміністратор бачить усе, а споживач —
лише власні виставлені рахунки в порталі.

Процес простий::

    Чернетка -> Розраховано -> Погоджено -> Виставлено
         \------------- Скасовано -------------/
                         |
                         +-> Чернетка

Для розрахунку система бере накопичувальні показники лічильників, зафіксовані
точно на перше число розрахункового місяця та перше число наступного місяця.
Демонстраційний приклад — один лікарняний вузол із п'ятьма об'єктами: корпусом 1,
лабораторією, корпусом 2 та двома аптеками. Головний лічильник вузла зафіксував
100 Гкал; власні лічильники корпусу 2 й Аптеки А зафіксували 30 і 10 Гкал, тому
решта 60 Гкал розподіляється між корпусом 1, лабораторією та Аптекою Б
пропорційно їхньому опалювальному об'єму як 30, 15 і 15 Гкал. У лікарні є
договір, тому до її нарахування входять власні об'єкти та 10 Гкал Аптеки А,
яка не має окремого договору: разом 85 Гкал. Аптека Б має власний договір і
отримує окреме нарахування на 15 Гкал; при цьому тариф кожного рядка визначає
категорія фактичного власника об'єкта, тому тепло Аптеки А навіть в нарахуванні
лікарні оцінюється за категорією аптеки.

Запуск
~~~~~~

З каталогу ``odoo_dev``::

    venv/bin/python odoo/odoo-bin --db_user=max-shelestiuk -d heat_demo --addons-path=odoo/addons,custom_addons/heat-energy-sales -i heat_energy_sales --with-demo --stop-after-init
    venv/bin/ruff check custom_addons/heat-energy-sales

Демо створює окрему компанію, усі стани нарахування, портал і три чернеткові
рахунки. Тут навмисно немає оплат, боргу, пені, прогнозних показників, погодних
коефіцієнтів та інтеграції з приладами.

Карта роботи
~~~~~~~~~~~~

.. list-table:: Де шукати виконання вимог курсової
   :header-rows: 1
   :widths: 15 31 54

   * - Вимога
     - Де реалізовано
     - Що саме перевірити
   * - 1. Моделі
     - ``models/heat_bill.py``; ``models/heat_bill_line.py``; ``models/consumer_category.py``; ``models/tariff.py``; ``models/supply_node.py``; ``models/supply_object.py``; ``models/meter.py``; ``models/meter_reading.py``
     - Є 8 постійних моделей: ``heat.bill`` проходить стани тільки серверними кнопками, ``heat.bill.line`` є окремою дочірньою сутністю, category і tariff — довідники; прямий стрибок станів та ручне редагування рядків заблоковані.
   * - 2. Представлення
     - ``views/configuration_views.xml``; ``views/metering_views.xml``; ``views/heat_bill_views.xml``; ``views/heat_bill_analysis_views.xml``
     - Кожна з 8 моделей має власні list/form та action; рядок нарахування відкривається окремо; для нарахувань є search, kanban, pivot і graph, для показників лічильників — search і graph; усі списки використовують Odoo 19 ``<list>``.
   * - 3. Меню
     - ``views/menus.xml``; ``static/description/icon.png``
     - Верхнє меню Heat Energy має власну PNG-іконку та веде до Operations, Metering, Consumers, Configuration і Reporting; демо наповнює кожний робочий розділ.
   * - 4. Наслідування
     - ``models/res_partner.py``; ``models/res_company.py``; ``models/account_move.py``; ``views/partner_company_views.xml``; ``views/account_move_views.xml``
     - ``res.partner`` зберігає категорію й договір, ``res.company`` — налаштування виставлення, ``account.move`` — унікальне посилання на нарахування; усі поля показані в UI та реально беруть участь у розрахунку, PDF або створенні рахунка.
   * - 5. Візард
     - ``wizard/generate_bills_wizard.py``; ``wizard/generate_bills_wizard_views.xml``
     - ``heat.bill.generate.wizard`` є TransientModel, запускається з меню, відбирає компанію/місяць/вузли/споживачів і атомарно формує повний набір пов'язаних нарахувань, не перезаписуючи проведені документи.
   * - 6. Звіт
     - ``report/heat_bill_report.xml``; ``report/heat_bill_templates.xml``; ``report/heat_bill_report.py``
     - QWeb PDF містить компанію, договір, період, об'єкти, метод, Гкал, тариф і суми; пакет із трьох нарахувань дає три окремі сторінки з власними шапкою та футером і не змінює стандартний layout Odoo.
   * - 7. Демо-дані
     - ``demo/hospital_demo.xml``; ``demo/billing_demo.xml``; ``models/demo_setup.py``; ``__manifest__.py``
     - Файли підключені через ключ ``demo``; є щонайменше 3 записи кожної нової моделі, усі 5 станів, лікарняний баланс 85 + 15 = 100 Гкал і заповнені дані для порталу, аналітики та PDF.
   * - 8. Тести
     - ``tests/test_configuration.py``; ``tests/test_metering.py``; ``tests/test_billing.py``; ``tests/test_wizard_invoice.py``; ``tests/test_portal_report.py``; ``tests/test_acceptance.py``
     - 54 тестові методи покривають кожну нову модель, переходи, помилки з текстом, ``with_user(...)``, баланс, конкурентні транзакції, портал, PDF та бухгалтерський рахунок; навмисна підміна правила тарифу справді ламає інтеграційний тест.
   * - 9. Права доступу
     - ``security/heat_security.xml``; ``security/ir.model.access.csv``; ``tests/test_metering.py``; ``tests/test_billing.py``
     - В одній категорії є User, Controller, Sales і Admin з ``implied_ids``; ACL не видані ``base.group_user``; правила звужують доступ до показників контролера, нарахувань збуту та portal-записів, а тести доводять, що Admin бачить більше за звичайного користувача.
   * - 10. Документація
     - ``README.rst``; ``static/description/index.html``; ``static/description/overview.png``; Python-файли в ``models/``, ``wizard/``, ``controllers/`` і ``report/``
     - README є валідним reStructuredText із картою та інваріантом; локальний HTML показує реальне PNG-зображення; усі класи й методи мають змістовні docstring, а складні місця пояснюють причину блокування, округлення, замикання пов'язаних вузлів і перевірки snapshot-ів.
   * - 11. Переклади
     - ``i18n/uk.po``; ``tests/test_acceptance.py``
     - Англійські вихідні рядки мають експортований Odoo український каталог без порожніх перекладів; перевірка перемикає англійський та український контексти в обидва боки.
   * - 12. Якість коду
     - ``tests/``; ``../docs/VALIDATION.md``; ``migrations/19.0.7.5.0/post-migrate.py``
     - Ruff проходить без помилок; чисті install/upgrade/uninstall перевірені з demo і без demo; код використовує ORM, ``models.Constraint``/``UniqueIndex``, ``Command`` і Monetary, не робить ручних commit та не покладається на onchange для захисту правил.

13. Інваріант предметної області
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Для кожного вузла й місяця сума Гкал у всіх рядках усіх пов'язаних нарахувань
має точно дорівнювати різниці показників головного лічильника з точністю до
0,000001 Гкал: тепло не може загубитися або бути нараховане двічі. Простого
обмеження бази тут недостатньо, бо правило охоплює показники лічильників,
об'єкти теплопостачання, рядки нарахувань та рахунки різних споживачів, тому
захист працює на кількох рівнях:

1. `Серверний розрахунок у _prepare_calculation() (models/heat_bill.py:181) <models/heat_bill.py#L181>`_
   використовує накопичувальні показники, зняті точно на перший день
   розрахункового місяця та перший день наступного місяця, а всі операції
   виконує за допомогою ``Decimal`` із точністю до 0,000001 Гкал, щоб уникнути
   похибок чисел із плаваючою комою; якщо після пропорційного розподілу тепла за
   опалювальним об'ємом залишається незначна різниця округлення, система додає
   її до останнього об'єкта без власного лічильника, завдяки чому сума всіх
   нарахованих обсягів точно дорівнює споживанню головного лічильника.

2. `Замикання пов'язаних вузлів у _connected_nodes() (models/heat_bill.py:326) <models/heat_bill.py#L326>`_
   автоматично додає до розрахунку всі пов'язані вузли та всіх споживачів, чиї
   об'єкти входять до спільного розподілу теплової енергії, тому система не
   дозволяє сформувати рахунок лише для одного споживача й залишити частину
   споживання поза загальним балансом; `метод _generate()
   (models/heat_bill.py:350) <models/heat_bill.py#L350>`_ створює всі пов'язані
   нарахування разом в одній транзакції — або успішно формується повний комплект
   документів, або в разі помилки не створюється жодного.

3. `Snapshot-перевірка у _validate_balance() (models/heat_bill.py:438) <models/heat_bill.py#L438>`_
   перед переходами **Approve** та **Issue** повторно порівнює поточні дані із
   зафіксованим результатом розрахунку. Система перевіряє, чи не були змінені
   або видалені початкові й кінцеві показники лічильників, чи збігаються
   кількість, об'єкт, тариф, ціна та інші дані кожної позиції з розрахунковим
   snapshot, а також чи збережені всі пов'язані нарахування інших споживачів за
   той самий вузол і місяць. Після цього вона ще раз підсумовує Гкал у всіх
   таких нарахуваннях і порівнює результат зі споживанням головного лічильника.
   Якщо хоча б одне джерело або позиція змінилися чи зникло пов'язане
   нарахування, погодження або виставлення блокується з вимогою виконати
   перерахунок.

4. База даних атомарно захищає прості правила предметної області за допомогою
   часткових унікальних індексів PostgreSQL. Для кожного вузла дозволено лише
   один активний головний лічильник — це забезпечує `_main_active_unique
   (models/meter.py:44) <models/meter.py#L44>`_. Один фізичний об'єкт може бути
   включений лише в одне нескасоване нарахування за конкретний місяць і компанію
   — правило реалізоване в `_object_month_unique (models/heat_bill_line.py:48)
   <models/heat_bill_line.py#L48>`_. Для одного споживача, компанії та місяця
   також може існувати лише одне нескасоване місячне нарахування — це контролює
   `_monthly_unique (models/heat_bill.py:68) <models/heat_bill.py#L68>`_.
   Скасовані записи не беруть участі в цих обмеженнях, тому після скасування
   розрахунок можна сформувати повторно. Оскільки правила перевіряє безпосередньо
   PostgreSQL під час запису, вони залишаються надійними навіть тоді, коли два
   користувачі одночасно намагаються створити конфліктні записи: база збереже
   перший допустимий запис, а другий відхилить як дублікат.

5. Перед створенням або зміною показників і перед розрахунком нарахувань система
   викликає `_lock_heat_billing() (models/res_company.py:29)
   <models/res_company.py#L29>`_. Метод виконує технічний ``UPDATE`` рядка
   відповідної компанії в таблиці ``res_company``. Значення ``write_date``
   фактично не змінюється, але PostgreSQL однаково створює нову версію рядка та
   утримує його блокування до завершення транзакції. Розрахунок захоплює цей
   спільний замок у `heat.bill._generate() (models/heat_bill.py:350)
   <models/heat_bill.py#L350>`_, а створення і редагування показників — у
   `heat.meter.reading.create() (models/meter_reading.py:134)
   <models/meter_reading.py#L134>`_ та `heat.meter.reading.write()
   (models/meter_reading.py:166) <models/meter_reading.py#L166>`_.

   Звичайний рівень ізоляції транзакцій сам по собі цього не виправляє. Кожна
   транзакція бачить узгоджену версію даних, але вони змінюють різні таблиці:
   одна — ``heat_meter_reading``, інша — ``heat_bill`` і ``heat_bill_line``.
   Тому PostgreSQL не бачить прямого конфлікту бізнес-рядків і без спільного
   блокування може дозволити обом транзакціям завершитися.

   `_lock_heat_billing() (models/res_company.py:29) <models/res_company.py#L29>`_
   створює навмисну точку конфлікту — рядок ``res_company``. Незалежно від того,
   які бізнес-таблиці змінюють транзакції, операції однієї компанії змушені
   виконати ``UPDATE`` одного спільного рядка. Якщо друга транзакція приходить,
   поки перша ще працює, вона чекає звільнення блокування. Якщо при цьому друга
   транзакція вже була відкрита зі старим snapshot, після завершення першої
   PostgreSQL у режимі ``REPEATABLE READ`` не дозволяє їй продовжити запис на
   основі застарілої версії рядка та породжує помилку серіалізації; Odoo повторює
   весь запит, і розрахунок заново читає актуальні показники. Для різних компаній
   використовуються різні рядки ``res_company``, тому їхні розрахунки можуть
   виконуватися паралельно.

Перевірка не живе лише у формі чи ``onchange``, бо імпорт і RPC легко їх обходять.

English
-------

This module calculates monthly heat use, allocates it to supply objects,
creates heat bills and prepares a draft Odoo invoice. The “Controller” user
enters meter readings, the “Sales” user prepares and issues bills, the
administrator sees everything, and a consumer sees only their own issued bills
in the portal.

The workflow is deliberately small::

    Draft -> Calculated -> Approved -> Issued
      \----------- Cancelled -----------/
                       |
                       +-> Draft

The calculation uses cumulative meter readings recorded exactly on the first
day of the billing month and the first day of the following month. The demo
example is one hospital supply node with five objects: Building 1, a laboratory,
Building 2 and two pharmacies. The main meter records 100 Gcal; the dedicated
meters of Building 2 and Pharmacy A record 30 and 10 Gcal, so the remaining
60 Gcal is allocated among Building 1, the laboratory and Pharmacy B in
proportion to their heated volumes as 30, 15 and 15 Gcal. The hospital has a
contract, so its bill includes its own objects and the 10 Gcal used by Pharmacy
A, which has no separate contract: 85 Gcal in total. Pharmacy B has its own
contract and receives a separate 15 Gcal bill; each line still uses the actual
object owner's category, so Pharmacy A's heat is priced at the pharmacy
category even when it appears on the hospital's bill.

Run it
~~~~~~

From the ``odoo_dev`` directory::

    venv/bin/python odoo/odoo-bin --db_user=max-shelestiuk -d heat_demo --addons-path=odoo/addons,custom_addons/heat-energy-sales -i heat_energy_sales --with-demo --stop-after-init
    venv/bin/ruff check custom_addons/heat-energy-sales

Demo data creates a separate company, all workflow states, a portal user and
three draft invoices. Payments, debt, penalties, estimated readings, weather
coefficients and device integrations are intentionally outside this module.

Work map
~~~~~~~~

.. list-table:: Where each course requirement is implemented
   :header-rows: 1
   :widths: 15 31 54

   * - Requirement
     - Implementation
     - What to inspect
   * - 1. Models
     - ``models/heat_bill.py``; ``models/heat_bill_line.py``; ``models/consumer_category.py``; ``models/tariff.py``; ``models/supply_node.py``; ``models/supply_object.py``; ``models/meter.py``; ``models/meter_reading.py``
     - There are 8 persistent models: ``heat.bill`` moves through states only through server buttons, ``heat.bill.line`` is a standalone child entity, and category/tariff are reference models; state jumps and manual line edits are rejected.
   * - 2. Views
     - ``views/configuration_views.xml``; ``views/metering_views.xml``; ``views/heat_bill_views.xml``; ``views/heat_bill_analysis_views.xml``
     - All 8 models have their own list/form views and actions; bill lines open separately; bills add search, kanban, pivot and graph, readings add search and graph, and every Odoo 19 list uses ``<list>``.
   * - 3. Menus
     - ``views/menus.xml``; ``static/description/icon.png``
     - The top-level Heat Energy app has its own PNG icon and populated Operations, Metering, Consumers, Configuration and Reporting sections when demo data is loaded.
   * - 4. Inheritance
     - ``models/res_partner.py``; ``models/res_company.py``; ``models/account_move.py``; ``views/partner_company_views.xml``; ``views/account_move_views.xml``
     - ``res.partner`` stores category/contract data, ``res.company`` stores billing defaults, and ``account.move`` keeps the unique bill link; every added field appears in the UI and is used by calculation, PDF or invoice creation.
   * - 5. Wizard
     - ``wizard/generate_bills_wizard.py``; ``wizard/generate_bills_wizard_views.xml``
     - The TransientModel opens from the menu, filters company/month/nodes/consumers, and atomically generates the complete connected set without overwriting progressed documents.
   * - 6. Report
     - ``report/heat_bill_report.xml``; ``report/heat_bill_templates.xml``; ``report/heat_bill_report.py``
     - The QWeb PDF includes company, contract, period, objects, method, Gcal, tariff and totals; printing three bills creates three pages with their own header/footer and leaves Odoo's standard report layout untouched.
   * - 7. Demo data
     - ``demo/hospital_demo.xml``; ``demo/billing_demo.xml``; ``models/demo_setup.py``; ``__manifest__.py``
     - Files are loaded through the manifest's ``demo`` key; every new model has at least 3 records, all 5 states exist, the hospital proves 85 + 15 = 100 Gcal, and portal/analysis/PDF fields are filled.
   * - 8. Tests
     - ``tests/test_configuration.py``; ``tests/test_metering.py``; ``tests/test_billing.py``; ``tests/test_wizard_invoice.py``; ``tests/test_portal_report.py``; ``tests/test_acceptance.py``
     - 54 test methods cover every new model, transitions, error text, ``with_user(...)``, balancing, concurrent transactions, portal, PDF and accounting; deliberately choosing the billing consumer's tariff makes the integration test fail.
   * - 9. Access rights
     - ``security/heat_security.xml``; ``security/ir.model.access.csv``; ``tests/test_metering.py``; ``tests/test_billing.py``
     - User, Controller, Sales and Admin share one category and use ``implied_ids``; no ACL uses ``base.group_user``; record rules restrict controller readings, assigned Sales bills and portal records, while tests prove Admin sees more.
   * - 10. Documentation
     - ``README.rst``; ``static/description/index.html``; ``static/description/overview.png``; Python files under ``models/``, ``wizard/``, ``controllers/`` and ``report/``
     - The README is valid reStructuredText with this map and the invariant; local HTML displays a real PNG; every class/method has a useful docstring, and comments explain locking, rounding, connected-node closure and snapshot validation.
   * - 11. Translations
     - ``i18n/uk.po``; ``tests/test_acceptance.py``
     - English source strings have an Odoo-exported Ukrainian catalogue with no empty translations; verification switches English and Ukrainian contexts both ways.
   * - 12. Code quality
     - ``tests/``; ``../docs/VALIDATION.md``; ``migrations/19.0.7.5.0/post-migrate.py``
     - Ruff passes; clean install, upgrade and uninstall were checked with and without demo; the code uses ORM, ``models.Constraint``/``UniqueIndex``, ``Command`` and Monetary, with no manual commit or onchange-only protection.

13. Domain invariant
~~~~~~~~~~~~~~~~~~~~

For every node and month, the Gcal total across all lines of all companion
bills must equal the main meter delta to 0.000001 Gcal, so heat is neither lost
nor billed twice. A database constraint alone cannot express a rule spanning
meter readings, supply objects, bill lines and bills belonging to different
consumers, so protection works at several levels:

1. `The server calculation in _prepare_calculation() (models/heat_bill.py:181) <models/heat_bill.py#L181>`_
   uses cumulative readings taken exactly on the first day of the billing month
   and the first day of the following month. It performs all energy arithmetic
   with ``Decimal`` at a precision of 0.000001 Gcal to avoid binary floating-point
   errors. If proportional allocation by heated volume leaves a small rounding
   difference, the system adds it to the last object without its own meter, so
   the total allocated quantity exactly matches the main meter consumption.

2. `The connected-node closure in _connected_nodes() (models/heat_bill.py:326) <models/heat_bill.py#L326>`_
   automatically includes every related node and consumer whose objects take
   part in the shared heat allocation. The system therefore cannot generate a
   bill for only one consumer while leaving part of the consumption outside the
   overall balance. `The _generate() method (models/heat_bill.py:350)
   <models/heat_bill.py#L350>`_ creates all companion bills in one transaction:
   either the complete document set is created successfully, or an error leaves
   none of it behind.

3. `The snapshot check in _validate_balance() (models/heat_bill.py:438) <models/heat_bill.py#L438>`_
   compares current data with the recorded calculation again before **Approve**
   and **Issue**. It checks whether the opening or closing meter readings were
   changed or deleted; whether every line still has the same quantity, object,
   tariff, price and other snapshot values; and whether all companion bills of
   the other consumers still exist for the same node and month. It then totals
   the Gcal across those bills again and compares the result with main-meter
   consumption. If a source or line changed, or a companion bill disappeared,
   approval and issuing are blocked until the calculation is run again.

4. PostgreSQL partial unique indexes protect the simple domain rules atomically.
   Each node may have only one active main meter, enforced by
   `_main_active_unique (models/meter.py:44) <models/meter.py#L44>`_. A physical
   object may occur in only one non-cancelled bill for a given company and month,
   enforced by `_object_month_unique (models/heat_bill_line.py:48)
   <models/heat_bill_line.py#L48>`_. A consumer, company and month may likewise
   have only one non-cancelled monthly bill, enforced by `_monthly_unique
   (models/heat_bill.py:68) <models/heat_bill.py#L68>`_. Cancelled records are
   excluded, so a month can be generated again after cancellation. Because
   PostgreSQL checks these rules during the write itself, they remain reliable
   when two users create conflicting records concurrently: the first valid row
   is saved and the duplicate is rejected.

5. Before meter readings are created or changed, and before bills are calculated,
   the system calls `_lock_heat_billing() (models/res_company.py:29)
   <models/res_company.py#L29>`_. This method performs a technical ``UPDATE`` of
   the relevant row in ``res_company``. Its ``write_date`` value does not actually
   change, but PostgreSQL still creates a new row version and holds its lock until
   the transaction ends. Bill calculation takes this shared lock in
   `heat.bill._generate() (models/heat_bill.py:350) <models/heat_bill.py#L350>`_,
   while reading creation and editing take it in `heat.meter.reading.create()
   (models/meter_reading.py:134) <models/meter_reading.py#L134>`_ and
   `heat.meter.reading.write() (models/meter_reading.py:166)
   <models/meter_reading.py#L166>`_.

   Ordinary transaction isolation does not solve this on its own. Each
   transaction sees a consistent version of the data, but the transactions
   modify different tables: one changes ``heat_meter_reading``, while the other
   changes ``heat_bill`` and ``heat_bill_line``. PostgreSQL therefore sees no
   direct conflict between the business rows and could otherwise allow both
   transactions to finish.

   `_lock_heat_billing() (models/res_company.py:29) <models/res_company.py#L29>`_
   deliberately creates a shared conflict point: the ``res_company`` row.
   Regardless of which business tables they modify, operations for one company
   must update the same row. A second transaction waits while the first holds
   the lock. If it was already opened with an old snapshot, PostgreSQL in
   ``REPEATABLE READ`` mode raises a serialization error instead of letting it
   continue from that stale row version. Odoo retries the whole request, and the
   calculation reads the current meter values again. Different companies use
   different ``res_company`` rows, so their calculations can still run in
   parallel.

This check does not live only in a form or ``onchange``, because imports and RPC
calls can easily bypass them.

License: LGPL-3.
