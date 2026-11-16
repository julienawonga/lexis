-- SPDX-FileCopyrightText: Copyright (c) 2026, Julien Awonga.
-- SPDX-License-Identifier: Apache-2.0
--
-- Lexis-authored synthetic fixture: a regional equipment-rental company
-- ("Harbourline"). Invented for this repository, not derived from any public
-- dataset, so no model can have memorised it. Used by the held-out evaluation
-- set dev_tools/evals/cases/rentals.json.
--
-- Portable subset: runs unchanged on SQLite and PostgreSQL (plain CREATE TABLE
-- and INSERT, ISO date literals, no vendor types or functions). Data is explicit
-- and deterministic. It deliberately looks like a real, slightly messy system:
-- abbreviated column names, coded statuses, soft deletes, meaningful NULLs, one
-- date stored as text (DD/MM/YYYY), look-alike columns and an unrelated table.
--
-- Load into SQLite:
--   python -c "import sqlite3; sqlite3.connect('rentals.sqlite').executescript(open('dev_tools/fixtures/sql/rentals.sql', encoding='utf-8').read())"
-- Load into PostgreSQL (empty database): psql -f dev_tools/fixtures/sql/rentals.sql

CREATE TABLE branch (
    branch_id INTEGER PRIMARY KEY,
    br_code VARCHAR(3) NOT NULL,
    br_name VARCHAR(60) NOT NULL,
    region VARCHAR(20) NOT NULL,
    opened_on DATE NOT NULL,
    closed_on DATE
);

CREATE TABLE staff (
    staff_id INTEGER PRIMARY KEY,
    branch_id INTEGER NOT NULL REFERENCES branch (branch_id),
    full_nm VARCHAR(80) NOT NULL,
    role_cd VARCHAR(3) NOT NULL,
    hired_on DATE NOT NULL,
    mgr_id INTEGER REFERENCES staff (staff_id),
    deleted_at TIMESTAMP,
    phone VARCHAR(20)
);

CREATE TABLE customer (
    cust_id INTEGER PRIMARY KEY,
    cust_ref VARCHAR(10) NOT NULL,
    co_name VARCHAR(80),
    contact_nm VARCHAR(80) NOT NULL,
    home_branch_id INTEGER NOT NULL REFERENCES branch (branch_id),
    credit_lmt NUMERIC(10, 2),
    signup_dt DATE NOT NULL,
    tax_no VARCHAR(12),
    deleted_at TIMESTAMP
);

CREATE TABLE equip_category (
    cat_id INTEGER PRIMARY KEY,
    cat_nm VARCHAR(40) NOT NULL,
    cat_desc VARCHAR(120),
    heavy_flg INTEGER NOT NULL
);

CREATE TABLE equip_unit (
    unit_id INTEGER PRIMARY KEY,
    cat_id INTEGER NOT NULL REFERENCES equip_category (cat_id),
    branch_id INTEGER NOT NULL REFERENCES branch (branch_id),
    serial_no VARCHAR(12) NOT NULL,
    model_nm VARCHAR(40) NOT NULL,
    purch_dt DATE NOT NULL,
    purch_cost NUMERIC(10, 2) NOT NULL,
    day_rate NUMERIC(8, 2) NOT NULL,
    retired_on DATE,
    deleted_at TIMESTAMP
);

CREATE TABLE rental_status (
    stat_cd CHAR(1) PRIMARY KEY,
    stat_label VARCHAR(20) NOT NULL,
    is_open INTEGER NOT NULL
);

CREATE TABLE rental (
    rental_id INTEGER PRIMARY KEY,
    cust_id INTEGER NOT NULL REFERENCES customer (cust_id),
    branch_id INTEGER NOT NULL REFERENCES branch (branch_id),
    staff_id INTEGER NOT NULL REFERENCES staff (staff_id),
    stat_cd CHAR(1) NOT NULL REFERENCES rental_status (stat_cd),
    start_dt DATE NOT NULL,
    due_dt DATE NOT NULL,
    ret_dt DATE,
    deposit_amt NUMERIC(8, 2),
    deleted_at TIMESTAMP
);

CREATE TABLE rental_item (
    rental_id INTEGER NOT NULL REFERENCES rental (rental_id),
    unit_id INTEGER NOT NULL REFERENCES equip_unit (unit_id),
    days_billed INTEGER NOT NULL,
    line_amt NUMERIC(10, 2) NOT NULL,
    PRIMARY KEY (rental_id, unit_id)
);

CREATE TABLE invoice (
    inv_id INTEGER PRIMARY KEY,
    rental_id INTEGER NOT NULL REFERENCES rental (rental_id),
    cust_id INTEGER NOT NULL REFERENCES customer (cust_id),
    inv_dt DATE NOT NULL,
    inv_sub NUMERIC(10, 2) NOT NULL,
    inv_tax NUMERIC(10, 2) NOT NULL,
    inv_ttl NUMERIC(10, 2) NOT NULL,
    pay_stat CHAR(1) NOT NULL
);

CREATE TABLE payment (
    pay_id INTEGER PRIMARY KEY,
    inv_id INTEGER NOT NULL REFERENCES invoice (inv_id),
    pay_dt DATE NOT NULL,
    amt NUMERIC(10, 2) NOT NULL,
    method_cd VARCHAR(2) NOT NULL,
    deleted_at TIMESTAMP
);

CREATE TABLE maint_job (
    job_id INTEGER PRIMARY KEY,
    unit_id INTEGER NOT NULL REFERENCES equip_unit (unit_id),
    tech_id INTEGER NOT NULL REFERENCES staff (staff_id),
    job_dt VARCHAR(10) NOT NULL,
    job_type VARCHAR(3) NOT NULL,
    cost NUMERIC(8, 2),
    downtime_days INTEGER
);

CREATE TABLE legacy_export_log (
    log_id INTEGER PRIMARY KEY,
    logged_at TIMESTAMP NOT NULL,
    target_sys VARCHAR(20) NOT NULL,
    rows_sent INTEGER NOT NULL,
    note VARCHAR(40)
);

INSERT INTO branch (branch_id, br_code, br_name, region, opened_on, closed_on) VALUES (1, 'NRD', 'Northgate Depot', 'North', '2016-03-01', NULL);
INSERT INTO branch (branch_id, br_code, br_name, region, opened_on, closed_on) VALUES (2, 'HBR', 'Harbour Yard', 'Coast', '2018-06-15', NULL);
INSERT INTO branch (branch_id, br_code, br_name, region, opened_on, closed_on) VALUES (3, 'MIL', 'Millbrook Site', 'Central', '2019-09-01', NULL);
INSERT INTO branch (branch_id, br_code, br_name, region, opened_on, closed_on) VALUES (4, 'ESC', 'Eastcliff Hub', 'East', '2021-04-12', NULL);
INSERT INTO branch (branch_id, br_code, br_name, region, opened_on, closed_on) VALUES (5, 'SVL', 'Southvale Depot', 'South', '2022-08-22', '2025-06-30');

INSERT INTO staff (staff_id, branch_id, full_nm, role_cd, hired_on, mgr_id, deleted_at, phone) VALUES (1, 1, 'Ingrid Halvorsen', 'MGR', '2016-03-01', NULL, NULL, '555-0101');
INSERT INTO staff (staff_id, branch_id, full_nm, role_cd, hired_on, mgr_id, deleted_at, phone) VALUES (2, 1, 'Dario Costa', 'CTR', '2017-01-09', 1, NULL, '555-0102');
INSERT INTO staff (staff_id, branch_id, full_nm, role_cd, hired_on, mgr_id, deleted_at, phone) VALUES (3, 1, 'Hettie Prowse', 'TCH', '2017-05-02', 1, NULL, NULL);
INSERT INTO staff (staff_id, branch_id, full_nm, role_cd, hired_on, mgr_id, deleted_at, phone) VALUES (4, 2, 'Tomas Brandt', 'MGR', '2018-06-15', NULL, NULL, '555-0104');
INSERT INTO staff (staff_id, branch_id, full_nm, role_cd, hired_on, mgr_id, deleted_at, phone) VALUES (5, 2, 'Marek Sloan', 'CTR', '2019-02-11', 4, '2024-11-30 17:00:00', NULL);
INSERT INTO staff (staff_id, branch_id, full_nm, role_cd, hired_on, mgr_id, deleted_at, phone) VALUES (6, 2, 'Ugo Fenwick', 'TCH', '2018-08-01', 4, '2025-03-31 17:00:00', '555-0106');
INSERT INTO staff (staff_id, branch_id, full_nm, role_cd, hired_on, mgr_id, deleted_at, phone) VALUES (7, 3, 'Wanjiru Okafor', 'MGR', '2019-09-01', NULL, NULL, '555-0107');
INSERT INTO staff (staff_id, branch_id, full_nm, role_cd, hired_on, mgr_id, deleted_at, phone) VALUES (8, 3, 'Sabine Duarte', 'CTR', '2020-01-20', 7, NULL, '555-0108');
INSERT INTO staff (staff_id, branch_id, full_nm, role_cd, hired_on, mgr_id, deleted_at, phone) VALUES (9, 3, 'Kofi Baranov', 'DRV', '2020-06-08', 7, NULL, NULL);
INSERT INTO staff (staff_id, branch_id, full_nm, role_cd, hired_on, mgr_id, deleted_at, phone) VALUES (10, 4, 'Pavel Novak', 'MGR', '2021-04-12', NULL, NULL, NULL);
INSERT INTO staff (staff_id, branch_id, full_nm, role_cd, hired_on, mgr_id, deleted_at, phone) VALUES (11, 4, 'Rhea Lindqvist', 'TCH', '2021-07-05', 10, NULL, '555-0111');
INSERT INTO staff (staff_id, branch_id, full_nm, role_cd, hired_on, mgr_id, deleted_at, phone) VALUES (12, 4, 'Otis Maddox', 'CTR', '2022-02-14', 10, NULL, NULL);
INSERT INTO staff (staff_id, branch_id, full_nm, role_cd, hired_on, mgr_id, deleted_at, phone) VALUES (13, 5, 'Leona Marsh', 'MGR', '2022-08-22', NULL, '2025-07-15 09:00:00', NULL);

INSERT INTO customer (cust_id, cust_ref, co_name, contact_nm, home_branch_id, credit_lmt, signup_dt, tax_no, deleted_at) VALUES (1, 'RC-1004', 'Orchard Lane Builders', 'Alma Holt', 4, 10000.00, '2019-02-13', 'TX07013', NULL);
INSERT INTO customer (cust_id, cust_ref, co_name, contact_nm, home_branch_id, credit_lmt, signup_dt, tax_no, deleted_at) VALUES (2, 'RC-1008', 'Greywater Civil', 'Bruno Ode', 2, 15000.00, '2019-03-22', 'TX07026', NULL);
INSERT INTO customer (cust_id, cust_ref, co_name, contact_nm, home_branch_id, credit_lmt, signup_dt, tax_no, deleted_at) VALUES (3, 'RC-1012', 'Pinecrest Landscaping', 'Cleo Yates', 5, NULL, '2019-04-28', 'TX07039', NULL);
INSERT INTO customer (cust_id, cust_ref, co_name, contact_nm, home_branch_id, credit_lmt, signup_dt, tax_no, deleted_at) VALUES (4, 'RC-1012', 'Harrow & Finch Roofing', 'Dmitri Dahl', 3, 5000.00, '2019-06-04', 'TX07052', NULL);
INSERT INTO customer (cust_id, cust_ref, co_name, contact_nm, home_branch_id, credit_lmt, signup_dt, tax_no, deleted_at) VALUES (5, 'RC-1016', 'Blackmoor Quarry Ltd', 'Edda Kane', 1, 10000.00, '2019-07-11', 'TX07065', '2025-06-12 14:05:00');
INSERT INTO customer (cust_id, cust_ref, co_name, contact_nm, home_branch_id, credit_lmt, signup_dt, tax_no, deleted_at) VALUES (6, 'RC-1020', 'Saltmarsh Marine Works', 'Felix Shaw', 4, NULL, '2019-08-17', 'TX07078', NULL);
INSERT INTO customer (cust_id, cust_ref, co_name, contact_nm, home_branch_id, credit_lmt, signup_dt, tax_no, deleted_at) VALUES (7, 'RC-1024', 'Redfern Paving', 'Greta Crane', 2, 20000.00, '2019-09-23', 'TX07091', NULL);
INSERT INTO customer (cust_id, cust_ref, co_name, contact_nm, home_branch_id, credit_lmt, signup_dt, tax_no, deleted_at) VALUES (8, 'RC-1024', 'Copperfield Events', 'Hugo Gil', 5, 5000.00, '2019-10-30', 'TX07104', NULL);
INSERT INTO customer (cust_id, cust_ref, co_name, contact_nm, home_branch_id, credit_lmt, signup_dt, tax_no, deleted_at) VALUES (9, 'RC-1028', 'Tidewell Plumbing', 'Isla Nash', 3, NULL, '2019-12-06', 'TX07117', NULL);
INSERT INTO customer (cust_id, cust_ref, co_name, contact_nm, home_branch_id, credit_lmt, signup_dt, tax_no, deleted_at) VALUES (10, 'RC-1032', 'Ashgrove Demolition', 'Jorge Webb', 1, 15000.00, '2020-01-12', 'TX07130', NULL);
INSERT INTO customer (cust_id, cust_ref, co_name, contact_nm, home_branch_id, credit_lmt, signup_dt, tax_no, deleted_at) VALUES (11, 'RC-1036', 'Larkspur Gardens', 'Kira Cruz', 4, 20000.00, '2020-02-18', 'TX07143', NULL);
INSERT INTO customer (cust_id, cust_ref, co_name, contact_nm, home_branch_id, credit_lmt, signup_dt, tax_no, deleted_at) VALUES (12, 'RC-1036', 'Ironbridge Fabrication', 'Lars Joss', 2, NULL, '2020-03-26', 'TX07156', NULL);
INSERT INTO customer (cust_id, cust_ref, co_name, contact_nm, home_branch_id, credit_lmt, signup_dt, tax_no, deleted_at) VALUES (13, 'RC-1040', 'Northfield Drainage', 'Maeve Rudd', 5, 10000.00, '2020-05-02', 'TX07169', NULL);
INSERT INTO customer (cust_id, cust_ref, co_name, contact_nm, home_branch_id, credit_lmt, signup_dt, tax_no, deleted_at) VALUES (14, 'RC-1044', 'Stonehaven Masonry', 'Nils Birch', 3, 15000.00, '2020-06-08', 'TX07182', NULL);
INSERT INTO customer (cust_id, cust_ref, co_name, contact_nm, home_branch_id, credit_lmt, signup_dt, tax_no, deleted_at) VALUES (15, 'RC-1048', 'Brightwell Cleaning Co', 'Opal Frost', 1, NULL, '2020-07-15', 'TX07195', NULL);
INSERT INTO customer (cust_id, cust_ref, co_name, contact_nm, home_branch_id, credit_lmt, signup_dt, tax_no, deleted_at) VALUES (16, 'RC-1048', 'Kingfisher Marquees', 'Pedro Moss', 4, 5000.00, '2020-08-21', 'TX07208', NULL);
INSERT INTO customer (cust_id, cust_ref, co_name, contact_nm, home_branch_id, credit_lmt, signup_dt, tax_no, deleted_at) VALUES (17, 'RC-1052', 'Oakshott Timber Frame', 'Quinn Vane', 2, 10000.00, '2020-09-27', 'TX07221', '2025-06-12 14:05:00');
INSERT INTO customer (cust_id, cust_ref, co_name, contact_nm, home_branch_id, credit_lmt, signup_dt, tax_no, deleted_at) VALUES (18, 'RC-1056', 'Marlow Rail Services', 'Rosa Berg', 5, NULL, '2020-11-03', 'TX07234', NULL);
INSERT INTO customer (cust_id, cust_ref, co_name, contact_nm, home_branch_id, credit_lmt, signup_dt, tax_no, deleted_at) VALUES (19, 'RC-1060', 'Quayside Scaffolding Hire', 'Stefan Ivers', 3, 20000.00, '2020-12-10', 'TX07247', NULL);
INSERT INTO customer (cust_id, cust_ref, co_name, contact_nm, home_branch_id, credit_lmt, signup_dt, tax_no, deleted_at) VALUES (20, 'RC-1060', 'Fernhill Farms', 'Thea Pike', 1, 5000.00, '2021-01-16', 'TX07260', NULL);
INSERT INTO customer (cust_id, cust_ref, co_name, contact_nm, home_branch_id, credit_lmt, signup_dt, tax_no, deleted_at) VALUES (21, 'RC-1064', 'Bellweather Interiors', 'Uri Zane', 4, NULL, '2021-02-22', 'TX07273', NULL);
INSERT INTO customer (cust_id, cust_ref, co_name, contact_nm, home_branch_id, credit_lmt, signup_dt, tax_no, deleted_at) VALUES (22, 'RC-1068', 'Cinder Road Motors', 'Vera Ek', 2, 15000.00, '2021-03-31', 'TX07286', NULL);
INSERT INTO customer (cust_id, cust_ref, co_name, contact_nm, home_branch_id, credit_lmt, signup_dt, tax_no, deleted_at) VALUES (23, 'RC-1072', 'Hollis & Quigg Surveyors', 'Wim Lowe', 5, 20000.00, '2021-05-07', 'TX07299', NULL);
INSERT INTO customer (cust_id, cust_ref, co_name, contact_nm, home_branch_id, credit_lmt, signup_dt, tax_no, deleted_at) VALUES (24, 'RC-1072', 'Driftwood Pontoons', 'Xena Tate', 3, NULL, '2021-06-13', 'TX07312', NULL);
INSERT INTO customer (cust_id, cust_ref, co_name, contact_nm, home_branch_id, credit_lmt, signup_dt, tax_no, deleted_at) VALUES (25, 'RC-1076', 'Westmere Council Works', 'Yusuf Abbott', 1, 10000.00, '2021-07-20', 'TX07325', NULL);
INSERT INTO customer (cust_id, cust_ref, co_name, contact_nm, home_branch_id, credit_lmt, signup_dt, tax_no, deleted_at) VALUES (26, 'RC-1080', NULL, 'Anneliese Vogt', 4, NULL, '2021-08-26', NULL, NULL);
INSERT INTO customer (cust_id, cust_ref, co_name, contact_nm, home_branch_id, credit_lmt, signup_dt, tax_no, deleted_at) VALUES (27, 'RC-1084', NULL, 'Rafael Ortiz', 2, NULL, '2021-10-02', NULL, NULL);
INSERT INTO customer (cust_id, cust_ref, co_name, contact_nm, home_branch_id, credit_lmt, signup_dt, tax_no, deleted_at) VALUES (28, 'RC-1084', NULL, 'Bridget Callahan', 5, NULL, '2021-11-08', NULL, NULL);
INSERT INTO customer (cust_id, cust_ref, co_name, contact_nm, home_branch_id, credit_lmt, signup_dt, tax_no, deleted_at) VALUES (29, 'RC-1088', NULL, 'Samir Haddad', 3, NULL, '2021-12-15', NULL, NULL);
INSERT INTO customer (cust_id, cust_ref, co_name, contact_nm, home_branch_id, credit_lmt, signup_dt, tax_no, deleted_at) VALUES (30, 'RC-1092', NULL, 'Noor Whitlock', 1, NULL, '2022-01-21', NULL, NULL);
INSERT INTO customer (cust_id, cust_ref, co_name, contact_nm, home_branch_id, credit_lmt, signup_dt, tax_no, deleted_at) VALUES (31, 'RC-1096', NULL, 'Jonas Eklund', 4, NULL, '2022-02-27', NULL, '2025-02-12 14:05:00');
INSERT INTO customer (cust_id, cust_ref, co_name, contact_nm, home_branch_id, credit_lmt, signup_dt, tax_no, deleted_at) VALUES (32, 'RC-1096', NULL, 'Priya Venkat', 2, NULL, '2022-04-05', NULL, NULL);
INSERT INTO customer (cust_id, cust_ref, co_name, contact_nm, home_branch_id, credit_lmt, signup_dt, tax_no, deleted_at) VALUES (33, 'RC-1100', NULL, 'Gareth Pugh', 5, NULL, '2022-05-12', NULL, NULL);
INSERT INTO customer (cust_id, cust_ref, co_name, contact_nm, home_branch_id, credit_lmt, signup_dt, tax_no, deleted_at) VALUES (34, 'RC-1104', NULL, 'Mina Kozak', 3, NULL, '2022-06-18', NULL, NULL);
INSERT INTO customer (cust_id, cust_ref, co_name, contact_nm, home_branch_id, credit_lmt, signup_dt, tax_no, deleted_at) VALUES (35, 'RC-1108', NULL, 'Dominic Rae', 1, NULL, '2022-07-25', NULL, '2025-06-12 14:05:00');
INSERT INTO customer (cust_id, cust_ref, co_name, contact_nm, home_branch_id, credit_lmt, signup_dt, tax_no, deleted_at) VALUES (36, 'RC-1108', NULL, 'Tessa Lund', 4, NULL, '2022-08-31', NULL, NULL);

INSERT INTO equip_category (cat_id, cat_nm, cat_desc, heavy_flg) VALUES (1, 'Excavators', 'Tracked and wheeled diggers, 1 to 8 tonne', 1);
INSERT INTO equip_category (cat_id, cat_nm, cat_desc, heavy_flg) VALUES (2, 'Scaffolding', 'Frames, towers and boards by the set', 0);
INSERT INTO equip_category (cat_id, cat_nm, cat_desc, heavy_flg) VALUES (3, 'Generators', 'Portable power, 2 to 40 kVA', 0);
INSERT INTO equip_category (cat_id, cat_nm, cat_desc, heavy_flg) VALUES (4, 'Pressure Washers', 'Petrol and electric cleaning units', 0);
INSERT INTO equip_category (cat_id, cat_nm, cat_desc, heavy_flg) VALUES (5, 'Aerial Lifts', 'Scissor and boom platforms', 1);
INSERT INTO equip_category (cat_id, cat_nm, cat_desc, heavy_flg) VALUES (6, 'Concrete Mixers', 'Drum and pan mixers', 0);

INSERT INTO equip_unit (unit_id, cat_id, branch_id, serial_no, model_nm, purch_dt, purch_cost, day_rate, retired_on, deleted_at) VALUES (1, 1, 1, 'SN-14000', 'Kestrel K35', '2018-01-17', 28500.00, 185.00, NULL, NULL);
INSERT INTO equip_unit (unit_id, cat_id, branch_id, serial_no, model_nm, purch_dt, purch_cost, day_rate, retired_on, deleted_at) VALUES (2, 2, 3, 'SN-24037', 'Spanfast Tower 6m', '2018-03-19', 3069.00, 55.00, NULL, NULL);
INSERT INTO equip_unit (unit_id, cat_id, branch_id, serial_no, model_nm, purch_dt, purch_cost, day_rate, retired_on, deleted_at) VALUES (3, 3, 5, 'SN-34074', 'Voltaire V5', '2018-05-19', 3822.00, 48.00, NULL, NULL);
INSERT INTO equip_unit (unit_id, cat_id, branch_id, serial_no, model_nm, purch_dt, purch_cost, day_rate, retired_on, deleted_at) VALUES (4, 4, 2, 'SN-44111', 'Jetline J150', '2018-07-19', 1406.50, 32.00, NULL, NULL);
INSERT INTO equip_unit (unit_id, cat_id, branch_id, serial_no, model_nm, purch_dt, purch_cost, day_rate, retired_on, deleted_at) VALUES (5, 5, 4, 'SN-54148', 'Skyreach SR12', '2018-09-18', 14304.00, 120.00, NULL, NULL);
INSERT INTO equip_unit (unit_id, cat_id, branch_id, serial_no, model_nm, purch_dt, purch_cost, day_rate, retired_on, deleted_at) VALUES (6, 6, 2, 'SN-64185', 'Tumble T140', '2018-11-18', 1662.50, 36.00, NULL, NULL);
INSERT INTO equip_unit (unit_id, cat_id, branch_id, serial_no, model_nm, purch_dt, purch_cost, day_rate, retired_on, deleted_at) VALUES (7, 1, 4, 'SN-14222', 'Kestrel K80', '2019-01-18', 57528.00, 310.00, '2025-09-30', NULL);
INSERT INTO equip_unit (unit_id, cat_id, branch_id, serial_no, model_nm, purch_dt, purch_cost, day_rate, retired_on, deleted_at) VALUES (8, 2, 1, 'SN-24259', 'Spanfast Frame Set', '2019-03-20', 2200.00, 38.00, NULL, NULL);
INSERT INTO equip_unit (unit_id, cat_id, branch_id, serial_no, model_nm, purch_dt, purch_cost, day_rate, retired_on, deleted_at) VALUES (9, 3, 3, 'SN-34296', 'Voltaire V20', '2019-05-20', 9702.00, 95.00, NULL, NULL);
INSERT INTO equip_unit (unit_id, cat_id, branch_id, serial_no, model_nm, purch_dt, purch_cost, day_rate, retired_on, deleted_at) VALUES (10, 4, 5, 'SN-44333', 'Jetline J250', '2019-07-20', 2254.00, 44.00, NULL, NULL);
INSERT INTO equip_unit (unit_id, cat_id, branch_id, serial_no, model_nm, purch_dt, purch_cost, day_rate, retired_on, deleted_at) VALUES (11, 5, 3, 'SN-54370', 'Skyreach BX18', '2019-09-19', 37539.00, 225.00, NULL, NULL);
INSERT INTO equip_unit (unit_id, cat_id, branch_id, serial_no, model_nm, purch_dt, purch_cost, day_rate, retired_on, deleted_at) VALUES (12, 6, 5, 'SN-64407', 'Tumble T350', '2019-11-19', 3456.00, 58.00, NULL, NULL);
INSERT INTO equip_unit (unit_id, cat_id, branch_id, serial_no, model_nm, purch_dt, purch_cost, day_rate, retired_on, deleted_at) VALUES (13, 1, 2, 'SN-14444', 'Dunmore D18', '2020-01-19', 20330.00, 140.00, NULL, NULL);
INSERT INTO equip_unit (unit_id, cat_id, branch_id, serial_no, model_nm, purch_dt, purch_cost, day_rate, retired_on, deleted_at) VALUES (14, 2, 4, 'SN-24481', 'Spanfast Tower 6m', '2020-03-20', 2914.00, 55.00, NULL, NULL);
INSERT INTO equip_unit (unit_id, cat_id, branch_id, serial_no, model_nm, purch_dt, purch_cost, day_rate, retired_on, deleted_at) VALUES (15, 3, 1, 'SN-34518', 'Ardent A40', '2020-05-20', 17600.00, 160.00, NULL, NULL);
INSERT INTO equip_unit (unit_id, cat_id, branch_id, serial_no, model_nm, purch_dt, purch_cost, day_rate, retired_on, deleted_at) VALUES (16, 4, 4, 'SN-44555', 'Jetline J150', '2020-07-20', 1435.50, 32.00, NULL, NULL);
INSERT INTO equip_unit (unit_id, cat_id, branch_id, serial_no, model_nm, purch_dt, purch_cost, day_rate, retired_on, deleted_at) VALUES (17, 5, 1, 'SN-54592', 'Skyreach SR12', '2020-09-19', 14602.00, 120.00, NULL, NULL);
INSERT INTO equip_unit (unit_id, cat_id, branch_id, serial_no, model_nm, purch_dt, purch_cost, day_rate, retired_on, deleted_at) VALUES (18, 6, 3, 'SN-64629', 'Tumble T140', '2020-11-19', 1697.50, 36.00, NULL, NULL);
INSERT INTO equip_unit (unit_id, cat_id, branch_id, serial_no, model_nm, purch_dt, purch_cost, day_rate, retired_on, deleted_at) VALUES (19, 1, 5, 'SN-14666', 'Kestrel K35', '2021-01-19', 27360.00, 185.00, '2025-09-30', NULL);
INSERT INTO equip_unit (unit_id, cat_id, branch_id, serial_no, model_nm, purch_dt, purch_cost, day_rate, retired_on, deleted_at) VALUES (20, 2, 2, 'SN-24703', 'Spanfast Frame Set', '2021-03-21', 2090.00, 38.00, NULL, NULL);
INSERT INTO equip_unit (unit_id, cat_id, branch_id, serial_no, model_nm, purch_dt, purch_cost, day_rate, retired_on, deleted_at) VALUES (21, 3, 5, 'SN-34740', 'Voltaire V5', '2021-05-21', 3666.00, 48.00, NULL, NULL);
INSERT INTO equip_unit (unit_id, cat_id, branch_id, serial_no, model_nm, purch_dt, purch_cost, day_rate, retired_on, deleted_at) VALUES (22, 4, 2, 'SN-44777', 'Jetline J250', '2021-07-21', 2300.00, 44.00, NULL, NULL);
INSERT INTO equip_unit (unit_id, cat_id, branch_id, serial_no, model_nm, purch_dt, purch_cost, day_rate, retired_on, deleted_at) VALUES (23, 5, 4, 'SN-54814', 'Skyreach BX18', '2021-09-20', 38313.00, 225.00, NULL, NULL);
INSERT INTO equip_unit (unit_id, cat_id, branch_id, serial_no, model_nm, purch_dt, purch_cost, day_rate, retired_on, deleted_at) VALUES (24, 6, 1, 'SN-64851', 'Tumble T350', '2021-11-20', 3528.00, 58.00, NULL, NULL);
INSERT INTO equip_unit (unit_id, cat_id, branch_id, serial_no, model_nm, purch_dt, purch_cost, day_rate, retired_on, deleted_at) VALUES (25, 1, 3, 'SN-14888', 'Kestrel K80', '2022-01-20', 59364.00, 310.00, NULL, NULL);
INSERT INTO equip_unit (unit_id, cat_id, branch_id, serial_no, model_nm, purch_dt, purch_cost, day_rate, retired_on, deleted_at) VALUES (26, 2, 1, 'SN-24925', 'Spanfast Tower 6m', '2022-03-22', 2976.00, 55.00, NULL, NULL);
INSERT INTO equip_unit (unit_id, cat_id, branch_id, serial_no, model_nm, purch_dt, purch_cost, day_rate, retired_on, deleted_at) VALUES (27, 3, 3, 'SN-34962', 'Voltaire V20', '2022-05-22', 9310.00, 95.00, NULL, NULL);
INSERT INTO equip_unit (unit_id, cat_id, branch_id, serial_no, model_nm, purch_dt, purch_cost, day_rate, retired_on, deleted_at) VALUES (28, 4, 5, 'SN-44999', 'Jetline J150', '2022-07-22', 1363.00, 32.00, '2025-09-30', NULL);
INSERT INTO equip_unit (unit_id, cat_id, branch_id, serial_no, model_nm, purch_dt, purch_cost, day_rate, retired_on, deleted_at) VALUES (29, 5, 2, 'SN-55036', 'Skyreach SR12', '2022-09-21', 14900.00, 120.00, NULL, NULL);
INSERT INTO equip_unit (unit_id, cat_id, branch_id, serial_no, model_nm, purch_dt, purch_cost, day_rate, retired_on, deleted_at) VALUES (30, 6, 4, 'SN-65073', 'Tumble T140', '2022-11-21', 1732.50, 36.00, NULL, NULL);
INSERT INTO equip_unit (unit_id, cat_id, branch_id, serial_no, model_nm, purch_dt, purch_cost, day_rate, retired_on, deleted_at) VALUES (31, 1, 2, 'SN-15110', 'Dunmore D18', '2023-01-21', 20972.00, 140.00, NULL, NULL);
INSERT INTO equip_unit (unit_id, cat_id, branch_id, serial_no, model_nm, purch_dt, purch_cost, day_rate, retired_on, deleted_at) VALUES (32, 2, 4, 'SN-25147', 'Spanfast Frame Set', '2023-03-23', 2134.00, 38.00, NULL, NULL);
INSERT INTO equip_unit (unit_id, cat_id, branch_id, serial_no, model_nm, purch_dt, purch_cost, day_rate, retired_on, deleted_at) VALUES (33, 3, 1, 'SN-35184', 'Ardent A40', '2023-05-23', 16896.00, 160.00, NULL, NULL);
INSERT INTO equip_unit (unit_id, cat_id, branch_id, serial_no, model_nm, purch_dt, purch_cost, day_rate, retired_on, deleted_at) VALUES (34, 4, 3, 'SN-45221', 'Jetline J250', '2023-07-23', 2185.00, 44.00, NULL, NULL);
INSERT INTO equip_unit (unit_id, cat_id, branch_id, serial_no, model_nm, purch_dt, purch_cost, day_rate, retired_on, deleted_at) VALUES (35, 5, 5, 'SN-55258', 'Skyreach BX18', '2023-09-22', 36378.00, 225.00, NULL, '2024-02-14 11:30:00');
INSERT INTO equip_unit (unit_id, cat_id, branch_id, serial_no, model_nm, purch_dt, purch_cost, day_rate, retired_on, deleted_at) VALUES (36, 6, 3, 'SN-65295', 'Tumble T350', '2023-11-22', 3600.00, 58.00, NULL, '2024-02-14 11:30:00');

INSERT INTO rental_status (stat_cd, stat_label, is_open) VALUES ('A', 'Active', 1);
INSERT INTO rental_status (stat_cd, stat_label, is_open) VALUES ('C', 'Closed', 0);
INSERT INTO rental_status (stat_cd, stat_label, is_open) VALUES ('X', 'Cancelled', 0);

INSERT INTO rental (rental_id, cust_id, branch_id, staff_id, stat_cd, start_dt, due_dt, ret_dt, deposit_amt, deleted_at) VALUES (1, 8, 4, 10, 'C', '2024-01-08', '2024-01-17', '2024-01-17', NULL, NULL);
INSERT INTO rental (rental_id, cust_id, branch_id, staff_id, stat_cd, start_dt, due_dt, ret_dt, deposit_amt, deleted_at) VALUES (2, 15, 2, 4, 'C', '2024-01-14', '2024-01-18', '2024-01-19', 200.00, NULL);
INSERT INTO rental (rental_id, cust_id, branch_id, staff_id, stat_cd, start_dt, due_dt, ret_dt, deposit_amt, deleted_at) VALUES (3, 22, 5, 13, 'C', '2024-01-20', '2024-01-31', '2024-01-30', NULL, NULL);
INSERT INTO rental (rental_id, cust_id, branch_id, staff_id, stat_cd, start_dt, due_dt, ret_dt, deposit_amt, deleted_at) VALUES (4, 29, 3, 8, 'C', '2024-01-26', '2024-02-01', '2024-02-01', 100.00, NULL);
INSERT INTO rental (rental_id, cust_id, branch_id, staff_id, stat_cd, start_dt, due_dt, ret_dt, deposit_amt, deleted_at) VALUES (5, 4, 1, 1, 'X', '2024-02-01', '2024-02-14', NULL, NULL, NULL);
INSERT INTO rental (rental_id, cust_id, branch_id, staff_id, stat_cd, start_dt, due_dt, ret_dt, deposit_amt, deleted_at) VALUES (6, 11, 4, 12, 'C', '2024-02-07', '2024-02-15', '2024-02-15', NULL, NULL);
INSERT INTO rental (rental_id, cust_id, branch_id, staff_id, stat_cd, start_dt, due_dt, ret_dt, deposit_amt, deleted_at) VALUES (7, 18, 2, 5, 'C', '2024-02-13', '2024-02-16', '2024-02-18', 250.00, NULL);
INSERT INTO rental (rental_id, cust_id, branch_id, staff_id, stat_cd, start_dt, due_dt, ret_dt, deposit_amt, deleted_at) VALUES (8, 25, 5, 13, 'C', '2024-02-19', '2024-02-29', '2024-02-29', NULL, NULL);
INSERT INTO rental (rental_id, cust_id, branch_id, staff_id, stat_cd, start_dt, due_dt, ret_dt, deposit_amt, deleted_at) VALUES (9, 12, 3, 7, 'C', '2024-02-25', '2024-03-01', '2024-03-01', 150.00, NULL);
INSERT INTO rental (rental_id, cust_id, branch_id, staff_id, stat_cd, start_dt, due_dt, ret_dt, deposit_amt, deleted_at) VALUES (10, 7, 1, 2, 'C', '2024-03-02', '2024-03-14', '2024-03-15', NULL, NULL);
INSERT INTO rental (rental_id, cust_id, branch_id, staff_id, stat_cd, start_dt, due_dt, ret_dt, deposit_amt, deleted_at) VALUES (11, 14, 4, 10, 'C', '2024-03-08', '2024-03-15', '2024-03-14', NULL, NULL);
INSERT INTO rental (rental_id, cust_id, branch_id, staff_id, stat_cd, start_dt, due_dt, ret_dt, deposit_amt, deleted_at) VALUES (12, 21, 2, 4, 'C', '2024-03-14', '2024-03-16', '2024-03-16', 100.00, NULL);
INSERT INTO rental (rental_id, cust_id, branch_id, staff_id, stat_cd, start_dt, due_dt, ret_dt, deposit_amt, deleted_at) VALUES (13, 20, 5, 13, 'C', '2024-03-20', '2024-03-29', '2024-04-01', NULL, NULL);
INSERT INTO rental (rental_id, cust_id, branch_id, staff_id, stat_cd, start_dt, due_dt, ret_dt, deposit_amt, deleted_at) VALUES (14, 3, 3, 8, 'C', '2024-03-26', '2024-03-30', '2024-04-01', 200.00, '2024-12-02 08:15:00');
INSERT INTO rental (rental_id, cust_id, branch_id, staff_id, stat_cd, start_dt, due_dt, ret_dt, deposit_amt, deleted_at) VALUES (15, 10, 1, 1, 'C', '2024-04-01', '2024-04-12', '2024-04-14', NULL, NULL);
INSERT INTO rental (rental_id, cust_id, branch_id, staff_id, stat_cd, start_dt, due_dt, ret_dt, deposit_amt, deleted_at) VALUES (16, 17, 4, 12, 'X', '2024-04-07', '2024-04-13', NULL, NULL, NULL);
INSERT INTO rental (rental_id, cust_id, branch_id, staff_id, stat_cd, start_dt, due_dt, ret_dt, deposit_amt, deleted_at) VALUES (17, 24, 2, 5, 'C', '2024-04-13', '2024-04-26', '2024-04-26', 150.00, NULL);
INSERT INTO rental (rental_id, cust_id, branch_id, staff_id, stat_cd, start_dt, due_dt, ret_dt, deposit_amt, deleted_at) VALUES (18, 12, 5, 13, 'C', '2024-04-19', '2024-04-27', '2024-04-28', 200.00, NULL);
INSERT INTO rental (rental_id, cust_id, branch_id, staff_id, stat_cd, start_dt, due_dt, ret_dt, deposit_amt, deleted_at) VALUES (19, 6, 3, 7, 'C', '2024-04-25', '2024-04-28', '2024-04-27', 250.00, NULL);
INSERT INTO rental (rental_id, cust_id, branch_id, staff_id, stat_cd, start_dt, due_dt, ret_dt, deposit_amt, deleted_at) VALUES (20, 13, 1, 2, 'C', '2024-05-01', '2024-05-11', '2024-05-11', NULL, NULL);
INSERT INTO rental (rental_id, cust_id, branch_id, staff_id, stat_cd, start_dt, due_dt, ret_dt, deposit_amt, deleted_at) VALUES (21, 20, 4, 10, 'C', '2024-05-07', '2024-05-12', '2024-05-15', NULL, NULL);
INSERT INTO rental (rental_id, cust_id, branch_id, staff_id, stat_cd, start_dt, due_dt, ret_dt, deposit_amt, deleted_at) VALUES (22, 27, 2, 4, 'C', '2024-05-13', '2024-05-25', '2024-05-25', 200.00, NULL);
INSERT INTO rental (rental_id, cust_id, branch_id, staff_id, stat_cd, start_dt, due_dt, ret_dt, deposit_amt, deleted_at) VALUES (23, 2, 5, 13, 'C', '2024-05-19', '2024-05-26', '2024-05-28', NULL, NULL);
INSERT INTO rental (rental_id, cust_id, branch_id, staff_id, stat_cd, start_dt, due_dt, ret_dt, deposit_amt, deleted_at) VALUES (24, 9, 3, 8, 'C', '2024-05-25', '2024-05-27', '2024-05-27', 100.00, NULL);
INSERT INTO rental (rental_id, cust_id, branch_id, staff_id, stat_cd, start_dt, due_dt, ret_dt, deposit_amt, deleted_at) VALUES (25, 16, 1, 1, 'C', '2024-05-31', '2024-06-09', '2024-06-09', NULL, NULL);
INSERT INTO rental (rental_id, cust_id, branch_id, staff_id, stat_cd, start_dt, due_dt, ret_dt, deposit_amt, deleted_at) VALUES (26, 20, 4, 12, 'C', '2024-06-06', '2024-06-10', '2024-06-11', NULL, NULL);
INSERT INTO rental (rental_id, cust_id, branch_id, staff_id, stat_cd, start_dt, due_dt, ret_dt, deposit_amt, deleted_at) VALUES (27, 12, 2, 5, 'X', '2024-06-12', '2024-06-23', NULL, 250.00, NULL);
INSERT INTO rental (rental_id, cust_id, branch_id, staff_id, stat_cd, start_dt, due_dt, ret_dt, deposit_amt, deleted_at) VALUES (28, 5, 5, 13, 'C', '2024-06-18', '2024-06-24', '2024-06-24', NULL, NULL);
INSERT INTO rental (rental_id, cust_id, branch_id, staff_id, stat_cd, start_dt, due_dt, ret_dt, deposit_amt, deleted_at) VALUES (29, 12, 3, 7, 'C', '2024-06-24', '2024-07-07', '2024-07-10', 150.00, NULL);
INSERT INTO rental (rental_id, cust_id, branch_id, staff_id, stat_cd, start_dt, due_dt, ret_dt, deposit_amt, deleted_at) VALUES (30, 19, 1, 2, 'C', '2024-06-30', '2024-07-08', '2024-07-08', NULL, NULL);
INSERT INTO rental (rental_id, cust_id, branch_id, staff_id, stat_cd, start_dt, due_dt, ret_dt, deposit_amt, deleted_at) VALUES (31, 26, 4, 10, 'C', '2024-07-06', '2024-07-09', '2024-07-11', 250.00, NULL);
INSERT INTO rental (rental_id, cust_id, branch_id, staff_id, stat_cd, start_dt, due_dt, ret_dt, deposit_amt, deleted_at) VALUES (32, 1, 2, 4, 'C', '2024-07-12', '2024-07-22', '2024-07-22', NULL, NULL);
INSERT INTO rental (rental_id, cust_id, branch_id, staff_id, stat_cd, start_dt, due_dt, ret_dt, deposit_amt, deleted_at) VALUES (33, 8, 5, 13, 'C', '2024-07-18', '2024-07-23', '2024-07-23', NULL, NULL);
INSERT INTO rental (rental_id, cust_id, branch_id, staff_id, stat_cd, start_dt, due_dt, ret_dt, deposit_amt, deleted_at) VALUES (34, 15, 3, 8, 'C', '2024-07-24', '2024-08-05', '2024-08-06', 200.00, NULL);
INSERT INTO rental (rental_id, cust_id, branch_id, staff_id, stat_cd, start_dt, due_dt, ret_dt, deposit_amt, deleted_at) VALUES (35, 22, 1, 1, 'C', '2024-07-30', '2024-08-06', '2024-08-05', NULL, NULL);
INSERT INTO rental (rental_id, cust_id, branch_id, staff_id, stat_cd, start_dt, due_dt, ret_dt, deposit_amt, deleted_at) VALUES (36, 12, 4, 12, 'C', '2024-08-05', '2024-08-07', '2024-08-07', 100.00, NULL);
INSERT INTO rental (rental_id, cust_id, branch_id, staff_id, stat_cd, start_dt, due_dt, ret_dt, deposit_amt, deleted_at) VALUES (37, 4, 2, 5, 'C', '2024-08-11', '2024-08-20', '2024-08-23', NULL, NULL);
INSERT INTO rental (rental_id, cust_id, branch_id, staff_id, stat_cd, start_dt, due_dt, ret_dt, deposit_amt, deleted_at) VALUES (38, 11, 5, 13, 'X', '2024-08-17', '2024-08-21', NULL, NULL, NULL);
INSERT INTO rental (rental_id, cust_id, branch_id, staff_id, stat_cd, start_dt, due_dt, ret_dt, deposit_amt, deleted_at) VALUES (39, 20, 3, 7, 'C', '2024-08-23', '2024-09-03', '2024-09-05', NULL, NULL);
INSERT INTO rental (rental_id, cust_id, branch_id, staff_id, stat_cd, start_dt, due_dt, ret_dt, deposit_amt, deleted_at) VALUES (40, 25, 1, 2, 'C', '2024-08-29', '2024-09-04', '2024-09-04', NULL, NULL);
INSERT INTO rental (rental_id, cust_id, branch_id, staff_id, stat_cd, start_dt, due_dt, ret_dt, deposit_amt, deleted_at) VALUES (41, 32, 4, 10, 'C', '2024-09-04', '2024-09-17', '2024-09-17', 150.00, NULL);
INSERT INTO rental (rental_id, cust_id, branch_id, staff_id, stat_cd, start_dt, due_dt, ret_dt, deposit_amt, deleted_at) VALUES (42, 7, 2, 4, 'C', '2024-09-10', '2024-09-18', '2024-09-19', NULL, NULL);
INSERT INTO rental (rental_id, cust_id, branch_id, staff_id, stat_cd, start_dt, due_dt, ret_dt, deposit_amt, deleted_at) VALUES (43, 14, 5, 13, 'C', '2024-09-16', '2024-09-19', '2024-09-18', NULL, NULL);
INSERT INTO rental (rental_id, cust_id, branch_id, staff_id, stat_cd, start_dt, due_dt, ret_dt, deposit_amt, deleted_at) VALUES (44, 21, 3, 8, 'C', '2024-09-22', '2024-10-02', '2024-10-02', 100.00, NULL);
INSERT INTO rental (rental_id, cust_id, branch_id, staff_id, stat_cd, start_dt, due_dt, ret_dt, deposit_amt, deleted_at) VALUES (45, 12, 1, 1, 'C', '2024-09-28', '2024-10-03', '2024-10-06', 150.00, NULL);
INSERT INTO rental (rental_id, cust_id, branch_id, staff_id, stat_cd, start_dt, due_dt, ret_dt, deposit_amt, deleted_at) VALUES (46, 3, 4, 12, 'C', '2024-10-04', '2024-10-16', '2024-10-16', 200.00, NULL);
INSERT INTO rental (rental_id, cust_id, branch_id, staff_id, stat_cd, start_dt, due_dt, ret_dt, deposit_amt, deleted_at) VALUES (47, 10, 2, 5, 'C', '2024-10-10', '2024-10-17', '2024-10-19', NULL, NULL);
INSERT INTO rental (rental_id, cust_id, branch_id, staff_id, stat_cd, start_dt, due_dt, ret_dt, deposit_amt, deleted_at) VALUES (48, 17, 5, 13, 'C', '2024-10-16', '2024-10-18', '2024-10-20', NULL, '2024-12-02 08:15:00');
INSERT INTO rental (rental_id, cust_id, branch_id, staff_id, stat_cd, start_dt, due_dt, ret_dt, deposit_amt, deleted_at) VALUES (49, 24, 3, 7, 'X', '2024-10-22', '2024-10-31', NULL, 150.00, NULL);
INSERT INTO rental (rental_id, cust_id, branch_id, staff_id, stat_cd, start_dt, due_dt, ret_dt, deposit_amt, deleted_at) VALUES (50, 31, 1, 2, 'C', '2024-10-28', '2024-11-01', '2024-11-02', 200.00, NULL);
INSERT INTO rental (rental_id, cust_id, branch_id, staff_id, stat_cd, start_dt, due_dt, ret_dt, deposit_amt, deleted_at) VALUES (51, 6, 4, 10, 'C', '2024-11-03', '2024-11-14', '2024-11-13', 250.00, NULL);
INSERT INTO rental (rental_id, cust_id, branch_id, staff_id, stat_cd, start_dt, due_dt, ret_dt, deposit_amt, deleted_at) VALUES (52, 20, 2, 4, 'C', '2024-11-09', '2024-11-15', '2024-11-15', NULL, NULL);
INSERT INTO rental (rental_id, cust_id, branch_id, staff_id, stat_cd, start_dt, due_dt, ret_dt, deposit_amt, deleted_at) VALUES (53, 20, 5, 13, 'C', '2024-11-15', '2024-11-28', '2024-12-01', NULL, NULL);
INSERT INTO rental (rental_id, cust_id, branch_id, staff_id, stat_cd, start_dt, due_dt, ret_dt, deposit_amt, deleted_at) VALUES (54, 12, 3, 8, 'C', '2024-11-21', '2024-11-29', '2024-11-29', 200.00, NULL);
INSERT INTO rental (rental_id, cust_id, branch_id, staff_id, stat_cd, start_dt, due_dt, ret_dt, deposit_amt, deleted_at) VALUES (55, 2, 1, 1, 'C', '2024-11-27', '2024-11-30', '2024-12-02', NULL, NULL);
INSERT INTO rental (rental_id, cust_id, branch_id, staff_id, stat_cd, start_dt, due_dt, ret_dt, deposit_amt, deleted_at) VALUES (56, 9, 4, 12, 'C', '2024-12-03', '2024-12-13', '2024-12-13', 100.00, NULL);
INSERT INTO rental (rental_id, cust_id, branch_id, staff_id, stat_cd, start_dt, due_dt, ret_dt, deposit_amt, deleted_at) VALUES (57, 16, 2, 4, 'C', '2024-12-09', '2024-12-14', '2024-12-14', NULL, NULL);
INSERT INTO rental (rental_id, cust_id, branch_id, staff_id, stat_cd, start_dt, due_dt, ret_dt, deposit_amt, deleted_at) VALUES (58, 23, 5, 13, 'C', '2024-12-15', '2024-12-27', '2024-12-28', NULL, NULL);
INSERT INTO rental (rental_id, cust_id, branch_id, staff_id, stat_cd, start_dt, due_dt, ret_dt, deposit_amt, deleted_at) VALUES (59, 30, 3, 7, 'C', '2024-12-21', '2024-12-28', '2024-12-27', 250.00, NULL);
INSERT INTO rental (rental_id, cust_id, branch_id, staff_id, stat_cd, start_dt, due_dt, ret_dt, deposit_amt, deleted_at) VALUES (60, 5, 1, 2, 'X', '2024-12-27', '2024-12-29', NULL, NULL, NULL);
INSERT INTO rental (rental_id, cust_id, branch_id, staff_id, stat_cd, start_dt, due_dt, ret_dt, deposit_amt, deleted_at) VALUES (61, 12, 4, 10, 'C', '2025-01-02', '2025-01-11', '2025-01-14', 150.00, NULL);
INSERT INTO rental (rental_id, cust_id, branch_id, staff_id, stat_cd, start_dt, due_dt, ret_dt, deposit_amt, deleted_at) VALUES (62, 19, 2, 4, 'C', '2025-01-08', '2025-01-12', '2025-01-12', NULL, NULL);
INSERT INTO rental (rental_id, cust_id, branch_id, staff_id, stat_cd, start_dt, due_dt, ret_dt, deposit_amt, deleted_at) VALUES (63, 12, 5, 13, 'C', '2025-01-14', '2025-01-25', '2025-01-27', 250.00, NULL);
INSERT INTO rental (rental_id, cust_id, branch_id, staff_id, stat_cd, start_dt, due_dt, ret_dt, deposit_amt, deleted_at) VALUES (64, 1, 3, 8, 'C', '2025-01-20', '2025-01-26', '2025-01-26', NULL, NULL);
INSERT INTO rental (rental_id, cust_id, branch_id, staff_id, stat_cd, start_dt, due_dt, ret_dt, deposit_amt, deleted_at) VALUES (65, 20, 1, 1, 'C', '2025-01-26', '2025-02-08', '2025-02-08', NULL, NULL);
INSERT INTO rental (rental_id, cust_id, branch_id, staff_id, stat_cd, start_dt, due_dt, ret_dt, deposit_amt, deleted_at) VALUES (66, 15, 4, 12, 'C', '2025-02-01', '2025-02-09', '2025-02-10', 200.00, NULL);
INSERT INTO rental (rental_id, cust_id, branch_id, staff_id, stat_cd, start_dt, due_dt, ret_dt, deposit_amt, deleted_at) VALUES (67, 22, 2, 4, 'C', '2025-02-07', '2025-02-10', '2025-02-09', NULL, NULL);
INSERT INTO rental (rental_id, cust_id, branch_id, staff_id, stat_cd, start_dt, due_dt, ret_dt, deposit_amt, deleted_at) VALUES (68, 29, 5, 13, 'C', '2025-02-13', '2025-02-23', '2025-02-23', 100.00, NULL);
INSERT INTO rental (rental_id, cust_id, branch_id, staff_id, stat_cd, start_dt, due_dt, ret_dt, deposit_amt, deleted_at) VALUES (69, 4, 3, 7, 'C', '2025-02-19', '2025-02-24', '2025-02-27', NULL, NULL);
INSERT INTO rental (rental_id, cust_id, branch_id, staff_id, stat_cd, start_dt, due_dt, ret_dt, deposit_amt, deleted_at) VALUES (70, 11, 1, 2, 'C', '2025-02-25', '2025-03-09', '2025-03-09', NULL, NULL);
INSERT INTO rental (rental_id, cust_id, branch_id, staff_id, stat_cd, start_dt, due_dt, ret_dt, deposit_amt, deleted_at) VALUES (71, 18, 4, 10, 'X', '2025-03-03', '2025-03-10', NULL, 250.00, NULL);
INSERT INTO rental (rental_id, cust_id, branch_id, staff_id, stat_cd, start_dt, due_dt, ret_dt, deposit_amt, deleted_at) VALUES (72, 12, 2, 4, 'C', '2025-03-09', '2025-03-11', '2025-03-13', 100.00, '2024-12-02 08:15:00');
INSERT INTO rental (rental_id, cust_id, branch_id, staff_id, stat_cd, start_dt, due_dt, ret_dt, deposit_amt, deleted_at) VALUES (73, 32, 5, 13, 'C', '2025-03-15', '2025-03-24', '2025-03-24', 150.00, NULL);
INSERT INTO rental (rental_id, cust_id, branch_id, staff_id, stat_cd, start_dt, due_dt, ret_dt, deposit_amt, deleted_at) VALUES (74, 7, 3, 8, 'C', '2025-03-21', '2025-03-25', '2025-03-26', NULL, NULL);
INSERT INTO rental (rental_id, cust_id, branch_id, staff_id, stat_cd, start_dt, due_dt, ret_dt, deposit_amt, deleted_at) VALUES (75, 14, 1, 1, 'C', '2025-03-27', '2025-04-07', '2025-04-06', NULL, NULL);
INSERT INTO rental (rental_id, cust_id, branch_id, staff_id, stat_cd, start_dt, due_dt, ret_dt, deposit_amt, deleted_at) VALUES (76, 21, 4, 12, 'C', '2025-04-02', '2025-04-08', '2025-04-08', 100.00, NULL);
INSERT INTO rental (rental_id, cust_id, branch_id, staff_id, stat_cd, start_dt, due_dt, ret_dt, deposit_amt, deleted_at) VALUES (77, 28, 2, 4, 'C', '2025-04-08', '2025-04-21', '2025-04-24', 150.00, NULL);
INSERT INTO rental (rental_id, cust_id, branch_id, staff_id, stat_cd, start_dt, due_dt, ret_dt, deposit_amt, deleted_at) VALUES (78, 20, 5, 13, 'C', '2025-04-14', '2025-04-22', '2025-04-22', NULL, NULL);
INSERT INTO rental (rental_id, cust_id, branch_id, staff_id, stat_cd, start_dt, due_dt, ret_dt, deposit_amt, deleted_at) VALUES (79, 10, 3, 7, 'C', '2025-04-20', '2025-04-23', '2025-04-25', NULL, NULL);
INSERT INTO rental (rental_id, cust_id, branch_id, staff_id, stat_cd, start_dt, due_dt, ret_dt, deposit_amt, deleted_at) VALUES (80, 17, 1, 2, 'C', '2025-04-26', '2025-05-06', '2025-05-06', NULL, NULL);
INSERT INTO rental (rental_id, cust_id, branch_id, staff_id, stat_cd, start_dt, due_dt, ret_dt, deposit_amt, deleted_at) VALUES (81, 12, 4, 10, 'C', '2025-05-02', '2025-05-07', '2025-05-07', 150.00, NULL);
INSERT INTO rental (rental_id, cust_id, branch_id, staff_id, stat_cd, start_dt, due_dt, ret_dt, deposit_amt, deleted_at) VALUES (82, 31, 2, 4, 'X', '2025-05-08', '2025-05-20', NULL, 200.00, NULL);
INSERT INTO rental (rental_id, cust_id, branch_id, staff_id, stat_cd, start_dt, due_dt, ret_dt, deposit_amt, deleted_at) VALUES (83, 6, 5, 13, 'A', '2025-05-14', '2025-05-21', NULL, 250.00, NULL);
INSERT INTO rental (rental_id, cust_id, branch_id, staff_id, stat_cd, start_dt, due_dt, ret_dt, deposit_amt, deleted_at) VALUES (84, 13, 3, 8, 'A', '2025-05-20', '2025-05-22', NULL, NULL, NULL);
INSERT INTO rental (rental_id, cust_id, branch_id, staff_id, stat_cd, start_dt, due_dt, ret_dt, deposit_amt, deleted_at) VALUES (85, 20, 1, 1, 'A', '2025-05-26', '2025-06-04', NULL, NULL, NULL);
INSERT INTO rental (rental_id, cust_id, branch_id, staff_id, stat_cd, start_dt, due_dt, ret_dt, deposit_amt, deleted_at) VALUES (86, 27, 4, 12, 'A', '2025-06-01', '2025-06-05', NULL, 200.00, NULL);
INSERT INTO rental (rental_id, cust_id, branch_id, staff_id, stat_cd, start_dt, due_dt, ret_dt, deposit_amt, deleted_at) VALUES (87, 2, 2, 4, 'A', '2025-06-07', '2025-06-18', NULL, NULL, NULL);
INSERT INTO rental (rental_id, cust_id, branch_id, staff_id, stat_cd, start_dt, due_dt, ret_dt, deposit_amt, deleted_at) VALUES (88, 9, 5, 13, 'A', '2025-06-13', '2025-06-19', NULL, 100.00, NULL);
INSERT INTO rental (rental_id, cust_id, branch_id, staff_id, stat_cd, start_dt, due_dt, ret_dt, deposit_amt, deleted_at) VALUES (89, 16, 3, 7, 'A', '2025-06-19', '2025-07-02', NULL, NULL, NULL);
INSERT INTO rental (rental_id, cust_id, branch_id, staff_id, stat_cd, start_dt, due_dt, ret_dt, deposit_amt, deleted_at) VALUES (90, 12, 1, 2, 'A', '2025-06-25', '2025-07-03', NULL, 200.00, NULL);

INSERT INTO rental_item (rental_id, unit_id, days_billed, line_amt) VALUES (1, 6, 9, 324.00);
INSERT INTO rental_item (rental_id, unit_id, days_billed, line_amt) VALUES (1, 17, 9, 1080.00);
INSERT INTO rental_item (rental_id, unit_id, days_billed, line_amt) VALUES (2, 11, 5, 1125.00);
INSERT INTO rental_item (rental_id, unit_id, days_billed, line_amt) VALUES (3, 16, 10, 320.00);
INSERT INTO rental_item (rental_id, unit_id, days_billed, line_amt) VALUES (3, 27, 10, 950.00);
INSERT INTO rental_item (rental_id, unit_id, days_billed, line_amt) VALUES (4, 21, 6, 288.00);
INSERT INTO rental_item (rental_id, unit_id, days_billed, line_amt) VALUES (5, 26, 0, 0.00);
INSERT INTO rental_item (rental_id, unit_id, days_billed, line_amt) VALUES (5, 5, 0, 0.00);
INSERT INTO rental_item (rental_id, unit_id, days_billed, line_amt) VALUES (6, 31, 8, 1120.00);
INSERT INTO rental_item (rental_id, unit_id, days_billed, line_amt) VALUES (7, 4, 5, 160.00);
INSERT INTO rental_item (rental_id, unit_id, days_billed, line_amt) VALUES (8, 9, 10, 950.00);
INSERT INTO rental_item (rental_id, unit_id, days_billed, line_amt) VALUES (9, 14, 5, 275.00);
INSERT INTO rental_item (rental_id, unit_id, days_billed, line_amt) VALUES (9, 25, 5, 1550.00);
INSERT INTO rental_item (rental_id, unit_id, days_billed, line_amt) VALUES (10, 19, 13, 2405.00);
INSERT INTO rental_item (rental_id, unit_id, days_billed, line_amt) VALUES (10, 30, 13, 468.00);
INSERT INTO rental_item (rental_id, unit_id, days_billed, line_amt) VALUES (11, 24, 6, 348.00);
INSERT INTO rental_item (rental_id, unit_id, days_billed, line_amt) VALUES (12, 29, 2, 240.00);
INSERT INTO rental_item (rental_id, unit_id, days_billed, line_amt) VALUES (13, 2, 12, 660.00);
INSERT INTO rental_item (rental_id, unit_id, days_billed, line_amt) VALUES (13, 13, 12, 1680.00);
INSERT INTO rental_item (rental_id, unit_id, days_billed, line_amt) VALUES (14, 7, 6, 1860.00);
INSERT INTO rental_item (rental_id, unit_id, days_billed, line_amt) VALUES (15, 12, 13, 754.00);
INSERT INTO rental_item (rental_id, unit_id, days_billed, line_amt) VALUES (16, 17, 0, 0.00);
INSERT INTO rental_item (rental_id, unit_id, days_billed, line_amt) VALUES (17, 22, 13, 572.00);
INSERT INTO rental_item (rental_id, unit_id, days_billed, line_amt) VALUES (17, 1, 13, 2405.00);
INSERT INTO rental_item (rental_id, unit_id, days_billed, line_amt) VALUES (17, 12, 13, 754.00);
INSERT INTO rental_item (rental_id, unit_id, days_billed, line_amt) VALUES (18, 27, 9, 855.00);
INSERT INTO rental_item (rental_id, unit_id, days_billed, line_amt) VALUES (19, 32, 2, 76.00);
INSERT INTO rental_item (rental_id, unit_id, days_billed, line_amt) VALUES (20, 5, 10, 1200.00);
INSERT INTO rental_item (rental_id, unit_id, days_billed, line_amt) VALUES (21, 10, 8, 352.00);
INSERT INTO rental_item (rental_id, unit_id, days_billed, line_amt) VALUES (21, 21, 8, 384.00);
INSERT INTO rental_item (rental_id, unit_id, days_billed, line_amt) VALUES (22, 15, 12, 1920.00);
INSERT INTO rental_item (rental_id, unit_id, days_billed, line_amt) VALUES (23, 20, 9, 342.00);
INSERT INTO rental_item (rental_id, unit_id, days_billed, line_amt) VALUES (24, 25, 2, 620.00);
INSERT INTO rental_item (rental_id, unit_id, days_billed, line_amt) VALUES (24, 4, 2, 64.00);
INSERT INTO rental_item (rental_id, unit_id, days_billed, line_amt) VALUES (25, 30, 9, 324.00);
INSERT INTO rental_item (rental_id, unit_id, days_billed, line_amt) VALUES (25, 9, 9, 855.00);
INSERT INTO rental_item (rental_id, unit_id, days_billed, line_amt) VALUES (26, 3, 5, 240.00);
INSERT INTO rental_item (rental_id, unit_id, days_billed, line_amt) VALUES (27, 8, 0, 0.00);
INSERT INTO rental_item (rental_id, unit_id, days_billed, line_amt) VALUES (28, 13, 6, 840.00);
INSERT INTO rental_item (rental_id, unit_id, days_billed, line_amt) VALUES (29, 18, 16, 576.00);
INSERT INTO rental_item (rental_id, unit_id, days_billed, line_amt) VALUES (29, 29, 16, 1920.00);
INSERT INTO rental_item (rental_id, unit_id, days_billed, line_amt) VALUES (30, 23, 8, 1800.00);
INSERT INTO rental_item (rental_id, unit_id, days_billed, line_amt) VALUES (31, 28, 5, 160.00);
INSERT INTO rental_item (rental_id, unit_id, days_billed, line_amt) VALUES (31, 7, 5, 1550.00);
INSERT INTO rental_item (rental_id, unit_id, days_billed, line_amt) VALUES (32, 1, 10, 1850.00);
INSERT INTO rental_item (rental_id, unit_id, days_billed, line_amt) VALUES (33, 6, 5, 180.00);
INSERT INTO rental_item (rental_id, unit_id, days_billed, line_amt) VALUES (33, 17, 5, 600.00);
INSERT INTO rental_item (rental_id, unit_id, days_billed, line_amt) VALUES (34, 11, 13, 2925.00);
INSERT INTO rental_item (rental_id, unit_id, days_billed, line_amt) VALUES (35, 16, 6, 192.00);
INSERT INTO rental_item (rental_id, unit_id, days_billed, line_amt) VALUES (36, 21, 2, 96.00);
INSERT INTO rental_item (rental_id, unit_id, days_billed, line_amt) VALUES (37, 26, 12, 660.00);
INSERT INTO rental_item (rental_id, unit_id, days_billed, line_amt) VALUES (37, 5, 12, 1440.00);
INSERT INTO rental_item (rental_id, unit_id, days_billed, line_amt) VALUES (38, 31, 0, 0.00);
INSERT INTO rental_item (rental_id, unit_id, days_billed, line_amt) VALUES (38, 10, 0, 0.00);
INSERT INTO rental_item (rental_id, unit_id, days_billed, line_amt) VALUES (39, 4, 13, 416.00);
INSERT INTO rental_item (rental_id, unit_id, days_billed, line_amt) VALUES (40, 9, 6, 570.00);
INSERT INTO rental_item (rental_id, unit_id, days_billed, line_amt) VALUES (41, 14, 13, 715.00);
INSERT INTO rental_item (rental_id, unit_id, days_billed, line_amt) VALUES (41, 25, 13, 4030.00);
INSERT INTO rental_item (rental_id, unit_id, days_billed, line_amt) VALUES (42, 19, 9, 1665.00);
INSERT INTO rental_item (rental_id, unit_id, days_billed, line_amt) VALUES (43, 24, 2, 116.00);
INSERT INTO rental_item (rental_id, unit_id, days_billed, line_amt) VALUES (44, 29, 10, 1200.00);
INSERT INTO rental_item (rental_id, unit_id, days_billed, line_amt) VALUES (45, 2, 8, 440.00);
INSERT INTO rental_item (rental_id, unit_id, days_billed, line_amt) VALUES (45, 13, 8, 1120.00);
INSERT INTO rental_item (rental_id, unit_id, days_billed, line_amt) VALUES (45, 24, 8, 464.00);
INSERT INTO rental_item (rental_id, unit_id, days_billed, line_amt) VALUES (46, 7, 12, 3720.00);
INSERT INTO rental_item (rental_id, unit_id, days_billed, line_amt) VALUES (47, 12, 9, 522.00);
INSERT INTO rental_item (rental_id, unit_id, days_billed, line_amt) VALUES (48, 17, 4, 480.00);
INSERT INTO rental_item (rental_id, unit_id, days_billed, line_amt) VALUES (49, 22, 0, 0.00);
INSERT INTO rental_item (rental_id, unit_id, days_billed, line_amt) VALUES (49, 1, 0, 0.00);
INSERT INTO rental_item (rental_id, unit_id, days_billed, line_amt) VALUES (50, 27, 5, 475.00);
INSERT INTO rental_item (rental_id, unit_id, days_billed, line_amt) VALUES (51, 32, 10, 380.00);
INSERT INTO rental_item (rental_id, unit_id, days_billed, line_amt) VALUES (52, 5, 6, 720.00);
INSERT INTO rental_item (rental_id, unit_id, days_billed, line_amt) VALUES (52, 16, 6, 192.00);
INSERT INTO rental_item (rental_id, unit_id, days_billed, line_amt) VALUES (53, 10, 16, 704.00);
INSERT INTO rental_item (rental_id, unit_id, days_billed, line_amt) VALUES (53, 21, 16, 768.00);
INSERT INTO rental_item (rental_id, unit_id, days_billed, line_amt) VALUES (54, 15, 8, 1280.00);
INSERT INTO rental_item (rental_id, unit_id, days_billed, line_amt) VALUES (55, 20, 5, 190.00);
INSERT INTO rental_item (rental_id, unit_id, days_billed, line_amt) VALUES (56, 25, 10, 3100.00);
INSERT INTO rental_item (rental_id, unit_id, days_billed, line_amt) VALUES (57, 30, 5, 180.00);
INSERT INTO rental_item (rental_id, unit_id, days_billed, line_amt) VALUES (57, 9, 5, 475.00);
INSERT INTO rental_item (rental_id, unit_id, days_billed, line_amt) VALUES (58, 3, 13, 624.00);
INSERT INTO rental_item (rental_id, unit_id, days_billed, line_amt) VALUES (59, 8, 6, 228.00);
INSERT INTO rental_item (rental_id, unit_id, days_billed, line_amt) VALUES (59, 19, 6, 1110.00);
INSERT INTO rental_item (rental_id, unit_id, days_billed, line_amt) VALUES (60, 13, 0, 0.00);
INSERT INTO rental_item (rental_id, unit_id, days_billed, line_amt) VALUES (61, 18, 12, 432.00);
INSERT INTO rental_item (rental_id, unit_id, days_billed, line_amt) VALUES (61, 29, 12, 1440.00);
INSERT INTO rental_item (rental_id, unit_id, days_billed, line_amt) VALUES (62, 23, 4, 900.00);
INSERT INTO rental_item (rental_id, unit_id, days_billed, line_amt) VALUES (63, 28, 13, 416.00);
INSERT INTO rental_item (rental_id, unit_id, days_billed, line_amt) VALUES (64, 1, 6, 1110.00);
INSERT INTO rental_item (rental_id, unit_id, days_billed, line_amt) VALUES (65, 6, 13, 468.00);
INSERT INTO rental_item (rental_id, unit_id, days_billed, line_amt) VALUES (65, 17, 13, 1560.00);
INSERT INTO rental_item (rental_id, unit_id, days_billed, line_amt) VALUES (66, 11, 9, 2025.00);
INSERT INTO rental_item (rental_id, unit_id, days_billed, line_amt) VALUES (66, 22, 9, 396.00);
INSERT INTO rental_item (rental_id, unit_id, days_billed, line_amt) VALUES (67, 16, 2, 64.00);
INSERT INTO rental_item (rental_id, unit_id, days_billed, line_amt) VALUES (68, 21, 10, 480.00);
INSERT INTO rental_item (rental_id, unit_id, days_billed, line_amt) VALUES (69, 26, 8, 440.00);
INSERT INTO rental_item (rental_id, unit_id, days_billed, line_amt) VALUES (69, 5, 8, 960.00);
INSERT INTO rental_item (rental_id, unit_id, days_billed, line_amt) VALUES (70, 31, 12, 1680.00);
INSERT INTO rental_item (rental_id, unit_id, days_billed, line_amt) VALUES (71, 4, 0, 0.00);
INSERT INTO rental_item (rental_id, unit_id, days_billed, line_amt) VALUES (72, 9, 4, 380.00);
INSERT INTO rental_item (rental_id, unit_id, days_billed, line_amt) VALUES (73, 14, 9, 495.00);
INSERT INTO rental_item (rental_id, unit_id, days_billed, line_amt) VALUES (73, 25, 9, 2790.00);
INSERT INTO rental_item (rental_id, unit_id, days_billed, line_amt) VALUES (73, 4, 9, 288.00);
INSERT INTO rental_item (rental_id, unit_id, days_billed, line_amt) VALUES (74, 19, 5, 925.00);
INSERT INTO rental_item (rental_id, unit_id, days_billed, line_amt) VALUES (75, 24, 10, 580.00);
INSERT INTO rental_item (rental_id, unit_id, days_billed, line_amt) VALUES (76, 29, 6, 720.00);
INSERT INTO rental_item (rental_id, unit_id, days_billed, line_amt) VALUES (77, 2, 16, 880.00);
INSERT INTO rental_item (rental_id, unit_id, days_billed, line_amt) VALUES (77, 13, 16, 2240.00);
INSERT INTO rental_item (rental_id, unit_id, days_billed, line_amt) VALUES (78, 7, 8, 2480.00);
INSERT INTO rental_item (rental_id, unit_id, days_billed, line_amt) VALUES (79, 12, 5, 290.00);
INSERT INTO rental_item (rental_id, unit_id, days_billed, line_amt) VALUES (80, 17, 10, 1200.00);
INSERT INTO rental_item (rental_id, unit_id, days_billed, line_amt) VALUES (80, 28, 10, 320.00);
INSERT INTO rental_item (rental_id, unit_id, days_billed, line_amt) VALUES (81, 22, 5, 220.00);
INSERT INTO rental_item (rental_id, unit_id, days_billed, line_amt) VALUES (81, 1, 5, 925.00);
INSERT INTO rental_item (rental_id, unit_id, days_billed, line_amt) VALUES (82, 27, 0, 0.00);
INSERT INTO rental_item (rental_id, unit_id, days_billed, line_amt) VALUES (83, 32, 7, 266.00);
INSERT INTO rental_item (rental_id, unit_id, days_billed, line_amt) VALUES (84, 5, 2, 240.00);
INSERT INTO rental_item (rental_id, unit_id, days_billed, line_amt) VALUES (85, 10, 9, 396.00);
INSERT INTO rental_item (rental_id, unit_id, days_billed, line_amt) VALUES (85, 21, 9, 432.00);
INSERT INTO rental_item (rental_id, unit_id, days_billed, line_amt) VALUES (86, 15, 4, 640.00);
INSERT INTO rental_item (rental_id, unit_id, days_billed, line_amt) VALUES (87, 20, 11, 418.00);
INSERT INTO rental_item (rental_id, unit_id, days_billed, line_amt) VALUES (87, 31, 11, 1540.00);
INSERT INTO rental_item (rental_id, unit_id, days_billed, line_amt) VALUES (88, 25, 6, 1860.00);
INSERT INTO rental_item (rental_id, unit_id, days_billed, line_amt) VALUES (89, 30, 13, 468.00);
INSERT INTO rental_item (rental_id, unit_id, days_billed, line_amt) VALUES (89, 9, 13, 1235.00);
INSERT INTO rental_item (rental_id, unit_id, days_billed, line_amt) VALUES (90, 3, 8, 384.00);

INSERT INTO invoice (inv_id, rental_id, cust_id, inv_dt, inv_sub, inv_tax, inv_ttl, pay_stat) VALUES (1, 1, 8, '2024-01-17', 1404.00, 140.40, 1544.40, 'P');
INSERT INTO invoice (inv_id, rental_id, cust_id, inv_dt, inv_sub, inv_tax, inv_ttl, pay_stat) VALUES (2, 2, 15, '2024-01-19', 1125.00, 112.50, 1237.50, 'O');
INSERT INTO invoice (inv_id, rental_id, cust_id, inv_dt, inv_sub, inv_tax, inv_ttl, pay_stat) VALUES (3, 3, 22, '2024-01-30', 1270.00, 127.00, 1397.00, 'P');
INSERT INTO invoice (inv_id, rental_id, cust_id, inv_dt, inv_sub, inv_tax, inv_ttl, pay_stat) VALUES (4, 4, 29, '2024-02-01', 288.00, 28.80, 316.80, 'V');
INSERT INTO invoice (inv_id, rental_id, cust_id, inv_dt, inv_sub, inv_tax, inv_ttl, pay_stat) VALUES (5, 6, 11, '2024-02-15', 1120.00, 112.00, 1232.00, 'O');
INSERT INTO invoice (inv_id, rental_id, cust_id, inv_dt, inv_sub, inv_tax, inv_ttl, pay_stat) VALUES (6, 7, 18, '2024-02-18', 160.00, 16.00, 176.00, 'P');
INSERT INTO invoice (inv_id, rental_id, cust_id, inv_dt, inv_sub, inv_tax, inv_ttl, pay_stat) VALUES (7, 8, 25, '2024-02-29', 950.00, 95.00, 1045.00, 'P');
INSERT INTO invoice (inv_id, rental_id, cust_id, inv_dt, inv_sub, inv_tax, inv_ttl, pay_stat) VALUES (8, 9, 12, '2024-03-01', 1825.00, 182.50, 2007.50, 'P');
INSERT INTO invoice (inv_id, rental_id, cust_id, inv_dt, inv_sub, inv_tax, inv_ttl, pay_stat) VALUES (9, 10, 7, '2024-03-15', 2873.00, 287.30, 3160.30, 'P');
INSERT INTO invoice (inv_id, rental_id, cust_id, inv_dt, inv_sub, inv_tax, inv_ttl, pay_stat) VALUES (10, 11, 14, '2024-03-14', 348.00, 34.80, 382.80, 'O');
INSERT INTO invoice (inv_id, rental_id, cust_id, inv_dt, inv_sub, inv_tax, inv_ttl, pay_stat) VALUES (11, 12, 21, '2024-03-16', 240.00, 24.00, 264.00, 'O');
INSERT INTO invoice (inv_id, rental_id, cust_id, inv_dt, inv_sub, inv_tax, inv_ttl, pay_stat) VALUES (12, 13, 20, '2024-04-01', 2340.00, 234.00, 2574.00, 'P');
INSERT INTO invoice (inv_id, rental_id, cust_id, inv_dt, inv_sub, inv_tax, inv_ttl, pay_stat) VALUES (13, 15, 10, '2024-04-14', 754.00, 75.40, 829.40, 'P');
INSERT INTO invoice (inv_id, rental_id, cust_id, inv_dt, inv_sub, inv_tax, inv_ttl, pay_stat) VALUES (14, 17, 24, '2024-04-26', 3731.00, 373.10, 4104.10, 'V');
INSERT INTO invoice (inv_id, rental_id, cust_id, inv_dt, inv_sub, inv_tax, inv_ttl, pay_stat) VALUES (15, 18, 12, '2024-04-28', 855.00, 85.50, 940.50, 'O');
INSERT INTO invoice (inv_id, rental_id, cust_id, inv_dt, inv_sub, inv_tax, inv_ttl, pay_stat) VALUES (16, 19, 6, '2024-04-27', 76.00, 7.60, 83.60, 'P');
INSERT INTO invoice (inv_id, rental_id, cust_id, inv_dt, inv_sub, inv_tax, inv_ttl, pay_stat) VALUES (17, 20, 13, '2024-05-11', 1200.00, 120.00, 1320.00, 'O');
INSERT INTO invoice (inv_id, rental_id, cust_id, inv_dt, inv_sub, inv_tax, inv_ttl, pay_stat) VALUES (18, 21, 20, '2024-05-15', 736.00, 73.60, 809.60, 'P');
INSERT INTO invoice (inv_id, rental_id, cust_id, inv_dt, inv_sub, inv_tax, inv_ttl, pay_stat) VALUES (19, 22, 27, '2024-05-25', 1920.00, 192.00, 2112.00, 'P');
INSERT INTO invoice (inv_id, rental_id, cust_id, inv_dt, inv_sub, inv_tax, inv_ttl, pay_stat) VALUES (20, 23, 2, '2024-05-28', 342.00, 34.20, 376.20, 'P');
INSERT INTO invoice (inv_id, rental_id, cust_id, inv_dt, inv_sub, inv_tax, inv_ttl, pay_stat) VALUES (21, 24, 9, '2024-05-27', 684.00, 68.40, 752.40, 'O');
INSERT INTO invoice (inv_id, rental_id, cust_id, inv_dt, inv_sub, inv_tax, inv_ttl, pay_stat) VALUES (22, 25, 16, '2024-06-09', 1179.00, 117.90, 1296.90, 'P');
INSERT INTO invoice (inv_id, rental_id, cust_id, inv_dt, inv_sub, inv_tax, inv_ttl, pay_stat) VALUES (23, 26, 20, '2024-06-11', 240.00, 24.00, 264.00, 'P');
INSERT INTO invoice (inv_id, rental_id, cust_id, inv_dt, inv_sub, inv_tax, inv_ttl, pay_stat) VALUES (24, 28, 5, '2024-06-24', 840.00, 84.00, 924.00, 'P');
INSERT INTO invoice (inv_id, rental_id, cust_id, inv_dt, inv_sub, inv_tax, inv_ttl, pay_stat) VALUES (25, 29, 12, '2024-07-10', 2496.00, 249.60, 2745.60, 'O');
INSERT INTO invoice (inv_id, rental_id, cust_id, inv_dt, inv_sub, inv_tax, inv_ttl, pay_stat) VALUES (26, 30, 19, '2024-07-08', 1800.00, 180.00, 1980.00, 'V');
INSERT INTO invoice (inv_id, rental_id, cust_id, inv_dt, inv_sub, inv_tax, inv_ttl, pay_stat) VALUES (27, 31, 26, '2024-07-11', 1710.00, 171.00, 1881.00, 'P');
INSERT INTO invoice (inv_id, rental_id, cust_id, inv_dt, inv_sub, inv_tax, inv_ttl, pay_stat) VALUES (28, 32, 1, '2024-07-22', 1850.00, 185.00, 2035.00, 'P');
INSERT INTO invoice (inv_id, rental_id, cust_id, inv_dt, inv_sub, inv_tax, inv_ttl, pay_stat) VALUES (29, 33, 8, '2024-07-23', 780.00, 78.00, 858.00, 'P');
INSERT INTO invoice (inv_id, rental_id, cust_id, inv_dt, inv_sub, inv_tax, inv_ttl, pay_stat) VALUES (30, 34, 15, '2024-08-06', 2925.00, 292.50, 3217.50, 'P');
INSERT INTO invoice (inv_id, rental_id, cust_id, inv_dt, inv_sub, inv_tax, inv_ttl, pay_stat) VALUES (31, 35, 22, '2024-08-05', 192.00, 19.20, 211.20, 'P');
INSERT INTO invoice (inv_id, rental_id, cust_id, inv_dt, inv_sub, inv_tax, inv_ttl, pay_stat) VALUES (32, 36, 12, '2024-08-07', 96.00, 9.60, 105.60, 'O');
INSERT INTO invoice (inv_id, rental_id, cust_id, inv_dt, inv_sub, inv_tax, inv_ttl, pay_stat) VALUES (33, 37, 4, '2024-08-23', 2100.00, 210.00, 2310.00, 'P');
INSERT INTO invoice (inv_id, rental_id, cust_id, inv_dt, inv_sub, inv_tax, inv_ttl, pay_stat) VALUES (34, 39, 20, '2024-09-05', 416.00, 41.60, 457.60, 'P');
INSERT INTO invoice (inv_id, rental_id, cust_id, inv_dt, inv_sub, inv_tax, inv_ttl, pay_stat) VALUES (35, 40, 25, '2024-09-04', 570.00, 57.00, 627.00, 'P');
INSERT INTO invoice (inv_id, rental_id, cust_id, inv_dt, inv_sub, inv_tax, inv_ttl, pay_stat) VALUES (36, 41, 32, '2024-09-17', 4745.00, 474.50, 5219.50, 'P');
INSERT INTO invoice (inv_id, rental_id, cust_id, inv_dt, inv_sub, inv_tax, inv_ttl, pay_stat) VALUES (37, 42, 7, '2024-09-19', 1665.00, 166.50, 1831.50, 'O');
INSERT INTO invoice (inv_id, rental_id, cust_id, inv_dt, inv_sub, inv_tax, inv_ttl, pay_stat) VALUES (38, 43, 14, '2024-09-18', 116.00, 11.60, 127.60, 'V');
INSERT INTO invoice (inv_id, rental_id, cust_id, inv_dt, inv_sub, inv_tax, inv_ttl, pay_stat) VALUES (39, 44, 21, '2024-10-02', 1200.00, 120.00, 1320.00, 'P');
INSERT INTO invoice (inv_id, rental_id, cust_id, inv_dt, inv_sub, inv_tax, inv_ttl, pay_stat) VALUES (40, 45, 12, '2024-10-06', 2024.00, 202.40, 2226.40, 'P');
INSERT INTO invoice (inv_id, rental_id, cust_id, inv_dt, inv_sub, inv_tax, inv_ttl, pay_stat) VALUES (41, 46, 3, '2024-10-16', 3720.00, 372.00, 4092.00, 'P');
INSERT INTO invoice (inv_id, rental_id, cust_id, inv_dt, inv_sub, inv_tax, inv_ttl, pay_stat) VALUES (42, 47, 10, '2024-10-19', 522.00, 52.20, 574.20, 'O');
INSERT INTO invoice (inv_id, rental_id, cust_id, inv_dt, inv_sub, inv_tax, inv_ttl, pay_stat) VALUES (43, 50, 31, '2024-11-02', 475.00, 47.50, 522.50, 'P');
INSERT INTO invoice (inv_id, rental_id, cust_id, inv_dt, inv_sub, inv_tax, inv_ttl, pay_stat) VALUES (44, 51, 6, '2024-11-13', 380.00, 38.00, 418.00, 'P');
INSERT INTO invoice (inv_id, rental_id, cust_id, inv_dt, inv_sub, inv_tax, inv_ttl, pay_stat) VALUES (45, 52, 20, '2024-11-15', 912.00, 91.20, 1003.20, 'P');
INSERT INTO invoice (inv_id, rental_id, cust_id, inv_dt, inv_sub, inv_tax, inv_ttl, pay_stat) VALUES (46, 53, 20, '2024-12-01', 1472.00, 147.20, 1619.20, 'P');
INSERT INTO invoice (inv_id, rental_id, cust_id, inv_dt, inv_sub, inv_tax, inv_ttl, pay_stat) VALUES (47, 54, 12, '2024-11-29', 1280.00, 128.00, 1408.00, 'O');
INSERT INTO invoice (inv_id, rental_id, cust_id, inv_dt, inv_sub, inv_tax, inv_ttl, pay_stat) VALUES (48, 55, 2, '2024-12-02', 190.00, 19.00, 209.00, 'P');
INSERT INTO invoice (inv_id, rental_id, cust_id, inv_dt, inv_sub, inv_tax, inv_ttl, pay_stat) VALUES (49, 56, 9, '2024-12-13', 3100.00, 310.00, 3410.00, 'V');
INSERT INTO invoice (inv_id, rental_id, cust_id, inv_dt, inv_sub, inv_tax, inv_ttl, pay_stat) VALUES (50, 57, 16, '2024-12-14', 655.00, 65.50, 720.50, 'P');
INSERT INTO invoice (inv_id, rental_id, cust_id, inv_dt, inv_sub, inv_tax, inv_ttl, pay_stat) VALUES (51, 58, 23, '2024-12-28', 624.00, 62.40, 686.40, 'P');
INSERT INTO invoice (inv_id, rental_id, cust_id, inv_dt, inv_sub, inv_tax, inv_ttl, pay_stat) VALUES (52, 59, 30, '2024-12-27', 1338.00, 133.80, 1471.80, 'P');
INSERT INTO invoice (inv_id, rental_id, cust_id, inv_dt, inv_sub, inv_tax, inv_ttl, pay_stat) VALUES (53, 61, 12, '2025-01-14', 1872.00, 187.20, 2059.20, 'P');
INSERT INTO invoice (inv_id, rental_id, cust_id, inv_dt, inv_sub, inv_tax, inv_ttl, pay_stat) VALUES (54, 62, 19, '2025-01-12', 900.00, 90.00, 990.00, 'P');
INSERT INTO invoice (inv_id, rental_id, cust_id, inv_dt, inv_sub, inv_tax, inv_ttl, pay_stat) VALUES (55, 63, 12, '2025-01-27', 416.00, 41.60, 457.60, 'P');
INSERT INTO invoice (inv_id, rental_id, cust_id, inv_dt, inv_sub, inv_tax, inv_ttl, pay_stat) VALUES (56, 64, 1, '2025-01-26', 1110.00, 111.00, 1221.00, 'P');
INSERT INTO invoice (inv_id, rental_id, cust_id, inv_dt, inv_sub, inv_tax, inv_ttl, pay_stat) VALUES (57, 65, 20, '2025-02-08', 2028.00, 202.80, 2230.80, 'O');
INSERT INTO invoice (inv_id, rental_id, cust_id, inv_dt, inv_sub, inv_tax, inv_ttl, pay_stat) VALUES (58, 66, 15, '2025-02-10', 2421.00, 242.10, 2663.10, 'O');
INSERT INTO invoice (inv_id, rental_id, cust_id, inv_dt, inv_sub, inv_tax, inv_ttl, pay_stat) VALUES (59, 67, 22, '2025-02-09', 64.00, 6.40, 70.40, 'P');
INSERT INTO invoice (inv_id, rental_id, cust_id, inv_dt, inv_sub, inv_tax, inv_ttl, pay_stat) VALUES (60, 68, 29, '2025-02-23', 480.00, 48.00, 528.00, 'P');
INSERT INTO invoice (inv_id, rental_id, cust_id, inv_dt, inv_sub, inv_tax, inv_ttl, pay_stat) VALUES (61, 69, 4, '2025-02-27', 1400.00, 140.00, 1540.00, 'V');
INSERT INTO invoice (inv_id, rental_id, cust_id, inv_dt, inv_sub, inv_tax, inv_ttl, pay_stat) VALUES (62, 70, 11, '2025-03-09', 1680.00, 168.00, 1848.00, 'P');
INSERT INTO invoice (inv_id, rental_id, cust_id, inv_dt, inv_sub, inv_tax, inv_ttl, pay_stat) VALUES (63, 73, 32, '2025-03-24', 3573.00, 357.30, 3930.30, 'P');
INSERT INTO invoice (inv_id, rental_id, cust_id, inv_dt, inv_sub, inv_tax, inv_ttl, pay_stat) VALUES (64, 74, 7, '2025-03-26', 925.00, 92.50, 1017.50, 'O');
INSERT INTO invoice (inv_id, rental_id, cust_id, inv_dt, inv_sub, inv_tax, inv_ttl, pay_stat) VALUES (65, 75, 14, '2025-04-06', 580.00, 58.00, 638.00, 'P');
INSERT INTO invoice (inv_id, rental_id, cust_id, inv_dt, inv_sub, inv_tax, inv_ttl, pay_stat) VALUES (66, 76, 21, '2025-04-08', 720.00, 72.00, 792.00, 'P');
INSERT INTO invoice (inv_id, rental_id, cust_id, inv_dt, inv_sub, inv_tax, inv_ttl, pay_stat) VALUES (67, 77, 28, '2025-04-24', 3120.00, 312.00, 3432.00, 'P');
INSERT INTO invoice (inv_id, rental_id, cust_id, inv_dt, inv_sub, inv_tax, inv_ttl, pay_stat) VALUES (68, 78, 20, '2025-04-22', 2480.00, 248.00, 2728.00, 'O');
INSERT INTO invoice (inv_id, rental_id, cust_id, inv_dt, inv_sub, inv_tax, inv_ttl, pay_stat) VALUES (69, 79, 10, '2025-04-25', 290.00, 29.00, 319.00, 'P');
INSERT INTO invoice (inv_id, rental_id, cust_id, inv_dt, inv_sub, inv_tax, inv_ttl, pay_stat) VALUES (70, 80, 17, '2025-05-06', 1520.00, 152.00, 1672.00, 'P');
INSERT INTO invoice (inv_id, rental_id, cust_id, inv_dt, inv_sub, inv_tax, inv_ttl, pay_stat) VALUES (71, 81, 12, '2025-05-07', 1145.00, 114.50, 1259.50, 'P');

INSERT INTO payment (pay_id, inv_id, pay_dt, amt, method_cd, deleted_at) VALUES (1, 1, '2024-01-21', 1544.40, 'BT', NULL);
INSERT INTO payment (pay_id, inv_id, pay_dt, amt, method_cd, deleted_at) VALUES (2, 2, '2024-01-26', 618.75, 'CH', NULL);
INSERT INTO payment (pay_id, inv_id, pay_dt, amt, method_cd, deleted_at) VALUES (3, 3, '2024-02-05', 1397.00, 'CC', NULL);
INSERT INTO payment (pay_id, inv_id, pay_dt, amt, method_cd, deleted_at) VALUES (4, 3, '2024-02-03', 1397.00, 'CC', '2025-01-20 10:00:00');
INSERT INTO payment (pay_id, inv_id, pay_dt, amt, method_cd, deleted_at) VALUES (5, 6, '2024-02-27', 176.00, 'CC', NULL);
INSERT INTO payment (pay_id, inv_id, pay_dt, amt, method_cd, deleted_at) VALUES (6, 7, '2024-03-10', 1045.00, 'BT', NULL);
INSERT INTO payment (pay_id, inv_id, pay_dt, amt, method_cd, deleted_at) VALUES (7, 8, '2024-03-12', 2007.50, 'CH', NULL);
INSERT INTO payment (pay_id, inv_id, pay_dt, amt, method_cd, deleted_at) VALUES (8, 9, '2024-03-27', 3160.30, 'CC', NULL);
INSERT INTO payment (pay_id, inv_id, pay_dt, amt, method_cd, deleted_at) VALUES (9, 10, '2024-03-29', 191.40, 'BT', NULL);
INSERT INTO payment (pay_id, inv_id, pay_dt, amt, method_cd, deleted_at) VALUES (10, 12, '2024-04-16', 2574.00, 'CC', NULL);
INSERT INTO payment (pay_id, inv_id, pay_dt, amt, method_cd, deleted_at) VALUES (11, 13, '2024-04-30', 829.40, 'BT', NULL);
INSERT INTO payment (pay_id, inv_id, pay_dt, amt, method_cd, deleted_at) VALUES (12, 16, '2024-05-16', 83.60, 'BT', NULL);
INSERT INTO payment (pay_id, inv_id, pay_dt, amt, method_cd, deleted_at) VALUES (13, 18, '2024-06-05', 809.60, 'CC', NULL);
INSERT INTO payment (pay_id, inv_id, pay_dt, amt, method_cd, deleted_at) VALUES (14, 19, '2024-06-16', 2112.00, 'BT', NULL);
INSERT INTO payment (pay_id, inv_id, pay_dt, amt, method_cd, deleted_at) VALUES (15, 20, '2024-06-02', 225.72, 'CH', NULL);
INSERT INTO payment (pay_id, inv_id, pay_dt, amt, method_cd, deleted_at) VALUES (16, 20, '2024-06-14', 150.48, 'CC', NULL);
INSERT INTO payment (pay_id, inv_id, pay_dt, amt, method_cd, deleted_at) VALUES (17, 22, '2024-06-14', 1296.90, 'BT', NULL);
INSERT INTO payment (pay_id, inv_id, pay_dt, amt, method_cd, deleted_at) VALUES (18, 22, '2024-06-13', 1296.90, 'BT', '2025-01-20 10:00:00');
INSERT INTO payment (pay_id, inv_id, pay_dt, amt, method_cd, deleted_at) VALUES (19, 23, '2024-06-17', 264.00, 'CH', NULL);
INSERT INTO payment (pay_id, inv_id, pay_dt, amt, method_cd, deleted_at) VALUES (20, 24, '2024-07-01', 924.00, 'CC', NULL);
INSERT INTO payment (pay_id, inv_id, pay_dt, amt, method_cd, deleted_at) VALUES (21, 27, '2024-07-21', 1881.00, 'CC', NULL);
INSERT INTO payment (pay_id, inv_id, pay_dt, amt, method_cd, deleted_at) VALUES (22, 28, '2024-08-02', 2035.00, 'BT', NULL);
INSERT INTO payment (pay_id, inv_id, pay_dt, amt, method_cd, deleted_at) VALUES (23, 29, '2024-08-04', 858.00, 'CH', NULL);
INSERT INTO payment (pay_id, inv_id, pay_dt, amt, method_cd, deleted_at) VALUES (24, 30, '2024-08-12', 1930.50, 'CC', NULL);
INSERT INTO payment (pay_id, inv_id, pay_dt, amt, method_cd, deleted_at) VALUES (25, 30, '2024-08-24', 1287.00, 'BT', NULL);
INSERT INTO payment (pay_id, inv_id, pay_dt, amt, method_cd, deleted_at) VALUES (26, 31, '2024-08-19', 211.20, 'BT', NULL);
INSERT INTO payment (pay_id, inv_id, pay_dt, amt, method_cd, deleted_at) VALUES (27, 32, '2024-08-22', 52.80, 'CH', NULL);
INSERT INTO payment (pay_id, inv_id, pay_dt, amt, method_cd, deleted_at) VALUES (28, 33, '2024-09-08', 2310.00, 'CC', NULL);
INSERT INTO payment (pay_id, inv_id, pay_dt, amt, method_cd, deleted_at) VALUES (29, 34, '2024-09-22', 457.60, 'BT', NULL);
INSERT INTO payment (pay_id, inv_id, pay_dt, amt, method_cd, deleted_at) VALUES (30, 35, '2024-09-15', 376.20, 'CH', NULL);
INSERT INTO payment (pay_id, inv_id, pay_dt, amt, method_cd, deleted_at) VALUES (31, 35, '2024-09-27', 250.80, 'CC', NULL);
INSERT INTO payment (pay_id, inv_id, pay_dt, amt, method_cd, deleted_at) VALUES (32, 36, '2024-10-06', 5219.50, 'CC', NULL);
INSERT INTO payment (pay_id, inv_id, pay_dt, amt, method_cd, deleted_at) VALUES (33, 39, '2024-10-24', 1320.00, 'CC', NULL);
INSERT INTO payment (pay_id, inv_id, pay_dt, amt, method_cd, deleted_at) VALUES (34, 40, '2024-10-13', 1335.84, 'BT', NULL);
INSERT INTO payment (pay_id, inv_id, pay_dt, amt, method_cd, deleted_at) VALUES (35, 40, '2024-10-25', 890.56, 'CH', NULL);
INSERT INTO payment (pay_id, inv_id, pay_dt, amt, method_cd, deleted_at) VALUES (36, 41, '2024-10-20', 4092.00, 'CH', NULL);
INSERT INTO payment (pay_id, inv_id, pay_dt, amt, method_cd, deleted_at) VALUES (37, 42, '2024-11-02', 287.10, 'CC', NULL);
INSERT INTO payment (pay_id, inv_id, pay_dt, amt, method_cd, deleted_at) VALUES (38, 43, '2024-11-08', 522.50, 'BT', NULL);
INSERT INTO payment (pay_id, inv_id, pay_dt, amt, method_cd, deleted_at) VALUES (39, 44, '2024-11-20', 418.00, 'CH', NULL);
INSERT INTO payment (pay_id, inv_id, pay_dt, amt, method_cd, deleted_at) VALUES (40, 45, '2024-11-18', 601.92, 'CC', NULL);
INSERT INTO payment (pay_id, inv_id, pay_dt, amt, method_cd, deleted_at) VALUES (41, 45, '2024-11-30', 401.28, 'BT', NULL);
INSERT INTO payment (pay_id, inv_id, pay_dt, amt, method_cd, deleted_at) VALUES (42, 46, '2024-12-10', 1619.20, 'BT', NULL);
INSERT INTO payment (pay_id, inv_id, pay_dt, amt, method_cd, deleted_at) VALUES (43, 48, '2024-12-13', 209.00, 'CC', NULL);
INSERT INTO payment (pay_id, inv_id, pay_dt, amt, method_cd, deleted_at) VALUES (44, 50, '2024-12-22', 432.30, 'CH', NULL);
INSERT INTO payment (pay_id, inv_id, pay_dt, amt, method_cd, deleted_at) VALUES (45, 50, '2025-01-03', 288.20, 'CC', NULL);
INSERT INTO payment (pay_id, inv_id, pay_dt, amt, method_cd, deleted_at) VALUES (46, 51, '2025-01-11', 686.40, 'CC', NULL);
INSERT INTO payment (pay_id, inv_id, pay_dt, amt, method_cd, deleted_at) VALUES (47, 52, '2025-01-11', 1471.80, 'BT', NULL);
INSERT INTO payment (pay_id, inv_id, pay_dt, amt, method_cd, deleted_at) VALUES (48, 53, '2025-01-30', 2059.20, 'CH', NULL);
INSERT INTO payment (pay_id, inv_id, pay_dt, amt, method_cd, deleted_at) VALUES (49, 54, '2025-01-29', 990.00, 'CC', NULL);
INSERT INTO payment (pay_id, inv_id, pay_dt, amt, method_cd, deleted_at) VALUES (50, 55, '2025-01-31', 274.56, 'BT', NULL);
INSERT INTO payment (pay_id, inv_id, pay_dt, amt, method_cd, deleted_at) VALUES (51, 55, '2025-02-12', 183.04, 'CH', NULL);
INSERT INTO payment (pay_id, inv_id, pay_dt, amt, method_cd, deleted_at) VALUES (52, 56, '2025-02-14', 1221.00, 'CH', NULL);
INSERT INTO payment (pay_id, inv_id, pay_dt, amt, method_cd, deleted_at) VALUES (53, 58, '2025-02-18', 1331.55, 'BT', NULL);
INSERT INTO payment (pay_id, inv_id, pay_dt, amt, method_cd, deleted_at) VALUES (54, 59, '2025-03-03', 70.40, 'CH', NULL);
INSERT INTO payment (pay_id, inv_id, pay_dt, amt, method_cd, deleted_at) VALUES (55, 60, '2025-03-04', 316.80, 'CC', NULL);
INSERT INTO payment (pay_id, inv_id, pay_dt, amt, method_cd, deleted_at) VALUES (56, 60, '2025-03-16', 211.20, 'BT', NULL);
INSERT INTO payment (pay_id, inv_id, pay_dt, amt, method_cd, deleted_at) VALUES (57, 62, '2025-03-14', 1848.00, 'CH', NULL);
INSERT INTO payment (pay_id, inv_id, pay_dt, amt, method_cd, deleted_at) VALUES (58, 63, '2025-03-30', 3930.30, 'CC', NULL);
INSERT INTO payment (pay_id, inv_id, pay_dt, amt, method_cd, deleted_at) VALUES (59, 64, '2025-04-09', 508.75, 'BT', NULL);
INSERT INTO payment (pay_id, inv_id, pay_dt, amt, method_cd, deleted_at) VALUES (60, 65, '2025-04-11', 382.80, 'CH', NULL);
INSERT INTO payment (pay_id, inv_id, pay_dt, amt, method_cd, deleted_at) VALUES (61, 65, '2025-04-23', 255.20, 'CC', NULL);
INSERT INTO payment (pay_id, inv_id, pay_dt, amt, method_cd, deleted_at) VALUES (62, 66, '2025-04-17', 792.00, 'CC', NULL);
INSERT INTO payment (pay_id, inv_id, pay_dt, amt, method_cd, deleted_at) VALUES (63, 67, '2025-05-04', 3432.00, 'BT', NULL);
INSERT INTO payment (pay_id, inv_id, pay_dt, amt, method_cd, deleted_at) VALUES (64, 68, '2025-04-29', 1364.00, 'CH', NULL);
INSERT INTO payment (pay_id, inv_id, pay_dt, amt, method_cd, deleted_at) VALUES (65, 69, '2025-05-07', 319.00, 'CC', NULL);
INSERT INTO payment (pay_id, inv_id, pay_dt, amt, method_cd, deleted_at) VALUES (66, 70, '2025-05-16', 1003.20, 'BT', NULL);
INSERT INTO payment (pay_id, inv_id, pay_dt, amt, method_cd, deleted_at) VALUES (67, 70, '2025-05-28', 668.80, 'CH', NULL);
INSERT INTO payment (pay_id, inv_id, pay_dt, amt, method_cd, deleted_at) VALUES (68, 71, '2025-05-21', 1259.50, 'CH', NULL);

INSERT INTO maint_job (job_id, unit_id, tech_id, job_dt, job_type, cost, downtime_days) VALUES (1, 8, 6, '15/01/2024', 'REP', 202.50, 3);
INSERT INTO maint_job (job_id, unit_id, tech_id, job_dt, job_type, cost, downtime_days) VALUES (2, 15, 11, '28/01/2024', 'INS', 119.00, NULL);
INSERT INTO maint_job (job_id, unit_id, tech_id, job_dt, job_type, cost, downtime_days) VALUES (3, 22, 3, '10/02/2024', 'SVC', 156.50, 3);
INSERT INTO maint_job (job_id, unit_id, tech_id, job_dt, job_type, cost, downtime_days) VALUES (4, 29, 6, '23/02/2024', 'REP', 313.00, 0);
INSERT INTO maint_job (job_id, unit_id, tech_id, job_dt, job_type, cost, downtime_days) VALUES (5, 2, 11, '07/03/2024', 'INS', 230.50, NULL);
INSERT INTO maint_job (job_id, unit_id, tech_id, job_dt, job_type, cost, downtime_days) VALUES (6, 9, 3, '20/03/2024', 'SVC', 267.00, 0);
INSERT INTO maint_job (job_id, unit_id, tech_id, job_dt, job_type, cost, downtime_days) VALUES (7, 16, 6, '02/04/2024', 'REP', 424.50, 3);
INSERT INTO maint_job (job_id, unit_id, tech_id, job_dt, job_type, cost, downtime_days) VALUES (8, 23, 11, '15/04/2024', 'INS', 341.00, NULL);
INSERT INTO maint_job (job_id, unit_id, tech_id, job_dt, job_type, cost, downtime_days) VALUES (9, 30, 3, '28/04/2024', 'SVC', NULL, 3);
INSERT INTO maint_job (job_id, unit_id, tech_id, job_dt, job_type, cost, downtime_days) VALUES (10, 3, 6, '11/05/2024', 'REP', 535.00, 0);
INSERT INTO maint_job (job_id, unit_id, tech_id, job_dt, job_type, cost, downtime_days) VALUES (11, 10, 11, '24/05/2024', 'INS', 52.50, NULL);
INSERT INTO maint_job (job_id, unit_id, tech_id, job_dt, job_type, cost, downtime_days) VALUES (12, 17, 3, '06/06/2024', 'SVC', 89.00, 0);
INSERT INTO maint_job (job_id, unit_id, tech_id, job_dt, job_type, cost, downtime_days) VALUES (13, 24, 6, '19/06/2024', 'REP', 246.50, 3);
INSERT INTO maint_job (job_id, unit_id, tech_id, job_dt, job_type, cost, downtime_days) VALUES (14, 31, 11, '02/07/2024', 'INS', 163.00, NULL);
INSERT INTO maint_job (job_id, unit_id, tech_id, job_dt, job_type, cost, downtime_days) VALUES (15, 4, 3, '15/07/2024', 'SVC', 200.50, 3);
INSERT INTO maint_job (job_id, unit_id, tech_id, job_dt, job_type, cost, downtime_days) VALUES (16, 11, 6, '28/07/2024', 'REP', 357.00, 0);
INSERT INTO maint_job (job_id, unit_id, tech_id, job_dt, job_type, cost, downtime_days) VALUES (17, 18, 11, '10/08/2024', 'INS', 274.50, NULL);
INSERT INTO maint_job (job_id, unit_id, tech_id, job_dt, job_type, cost, downtime_days) VALUES (18, 25, 3, '23/08/2024', 'SVC', NULL, 0);
INSERT INTO maint_job (job_id, unit_id, tech_id, job_dt, job_type, cost, downtime_days) VALUES (19, 32, 6, '05/09/2024', 'REP', 468.50, 3);
INSERT INTO maint_job (job_id, unit_id, tech_id, job_dt, job_type, cost, downtime_days) VALUES (20, 5, 11, '18/09/2024', 'INS', 385.00, NULL);
INSERT INTO maint_job (job_id, unit_id, tech_id, job_dt, job_type, cost, downtime_days) VALUES (21, 12, 3, '01/10/2024', 'SVC', 422.50, 3);
INSERT INTO maint_job (job_id, unit_id, tech_id, job_dt, job_type, cost, downtime_days) VALUES (22, 19, 6, '14/10/2024', 'REP', 179.00, 0);
INSERT INTO maint_job (job_id, unit_id, tech_id, job_dt, job_type, cost, downtime_days) VALUES (23, 26, 11, '27/10/2024', 'INS', 96.50, NULL);
INSERT INTO maint_job (job_id, unit_id, tech_id, job_dt, job_type, cost, downtime_days) VALUES (24, 33, 3, '09/11/2024', 'SVC', 133.00, 0);
INSERT INTO maint_job (job_id, unit_id, tech_id, job_dt, job_type, cost, downtime_days) VALUES (25, 6, 6, '22/11/2024', 'REP', 290.50, 3);
INSERT INTO maint_job (job_id, unit_id, tech_id, job_dt, job_type, cost, downtime_days) VALUES (26, 13, 11, '05/12/2024', 'INS', 207.00, NULL);
INSERT INTO maint_job (job_id, unit_id, tech_id, job_dt, job_type, cost, downtime_days) VALUES (27, 20, 3, '18/12/2024', 'SVC', NULL, 3);
INSERT INTO maint_job (job_id, unit_id, tech_id, job_dt, job_type, cost, downtime_days) VALUES (28, 27, 6, '31/12/2024', 'REP', 401.00, 0);
INSERT INTO maint_job (job_id, unit_id, tech_id, job_dt, job_type, cost, downtime_days) VALUES (29, 34, 11, '13/01/2025', 'INS', 318.50, NULL);
INSERT INTO maint_job (job_id, unit_id, tech_id, job_dt, job_type, cost, downtime_days) VALUES (30, 7, 3, '26/01/2025', 'SVC', 355.00, 0);
INSERT INTO maint_job (job_id, unit_id, tech_id, job_dt, job_type, cost, downtime_days) VALUES (31, 14, 6, '08/02/2025', 'REP', 512.50, 3);
INSERT INTO maint_job (job_id, unit_id, tech_id, job_dt, job_type, cost, downtime_days) VALUES (32, 21, 11, '21/02/2025', 'INS', 429.00, NULL);
INSERT INTO maint_job (job_id, unit_id, tech_id, job_dt, job_type, cost, downtime_days) VALUES (33, 28, 3, '06/03/2025', 'SVC', 66.50, 3);
INSERT INTO maint_job (job_id, unit_id, tech_id, job_dt, job_type, cost, downtime_days) VALUES (34, 1, 6, '19/03/2025', 'REP', 223.00, 0);
INSERT INTO maint_job (job_id, unit_id, tech_id, job_dt, job_type, cost, downtime_days) VALUES (35, 8, 11, '01/04/2025', 'INS', 140.50, NULL);
INSERT INTO maint_job (job_id, unit_id, tech_id, job_dt, job_type, cost, downtime_days) VALUES (36, 15, 3, '14/04/2025', 'SVC', NULL, 0);
INSERT INTO maint_job (job_id, unit_id, tech_id, job_dt, job_type, cost, downtime_days) VALUES (37, 22, 3, '27/04/2025', 'REP', 334.50, 3);
INSERT INTO maint_job (job_id, unit_id, tech_id, job_dt, job_type, cost, downtime_days) VALUES (38, 29, 11, '10/05/2025', 'INS', 251.00, NULL);
INSERT INTO maint_job (job_id, unit_id, tech_id, job_dt, job_type, cost, downtime_days) VALUES (39, 2, 3, '23/05/2025', 'SVC', 288.50, 3);
INSERT INTO maint_job (job_id, unit_id, tech_id, job_dt, job_type, cost, downtime_days) VALUES (40, 9, 3, '05/06/2025', 'REP', 445.00, 0);

INSERT INTO legacy_export_log (log_id, logged_at, target_sys, rows_sent, note) VALUES (1, '2025-02-02 02:00:00', 'LEDGER-OLD', 137, NULL);
INSERT INTO legacy_export_log (log_id, logged_at, target_sys, rows_sent, note) VALUES (2, '2025-03-03 02:00:00', 'LEDGER-OLD', 154, NULL);
INSERT INTO legacy_export_log (log_id, logged_at, target_sys, rows_sent, note) VALUES (3, '2025-04-04 02:00:00', 'LEDGER-OLD', 171, 'retry');
INSERT INTO legacy_export_log (log_id, logged_at, target_sys, rows_sent, note) VALUES (4, '2025-05-05 02:00:00', 'LEDGER-OLD', 188, NULL);
INSERT INTO legacy_export_log (log_id, logged_at, target_sys, rows_sent, note) VALUES (5, '2025-06-06 02:00:00', 'LEDGER-OLD', 205, NULL);
INSERT INTO legacy_export_log (log_id, logged_at, target_sys, rows_sent, note) VALUES (6, '2025-07-07 02:00:00', 'LEDGER-OLD', 222, 'retry');
INSERT INTO legacy_export_log (log_id, logged_at, target_sys, rows_sent, note) VALUES (7, '2025-08-08 02:00:00', 'LEDGER-OLD', 239, NULL);
INSERT INTO legacy_export_log (log_id, logged_at, target_sys, rows_sent, note) VALUES (8, '2025-09-01 02:00:00', 'LEDGER-OLD', 256, NULL);
INSERT INTO legacy_export_log (log_id, logged_at, target_sys, rows_sent, note) VALUES (9, '2025-01-02 02:00:00', 'LEDGER-OLD', 273, 'retry');
INSERT INTO legacy_export_log (log_id, logged_at, target_sys, rows_sent, note) VALUES (10, '2025-02-03 02:00:00', 'LEDGER-OLD', 290, NULL);
