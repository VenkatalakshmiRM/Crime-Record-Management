import unittest
from pathlib import Path

from scripts.verify_mysql import parse_mysql_script


class MySQLScriptTests(unittest.TestCase):
    def test_parser_keeps_trigger_bodies_together_across_delimiters(self):
        statements = parse_mysql_script('''CREATE TABLE t (id INT);\nDELIMITER $$\nCREATE TRIGGER t_ai AFTER INSERT ON t FOR EACH ROW\nBEGIN\n  SET @seen = NEW.id;\nEND$$\nDELIMITER ;\nCREATE VIEW v AS SELECT id FROM t;\n''')
        self.assertEqual(len(statements), 3)
        self.assertEqual(statements[0], 'CREATE TABLE t (id INT)')
        self.assertIn('SET @seen = NEW.id;', statements[1])
        self.assertTrue(statements[1].endswith('END'))
        self.assertEqual(statements[2], 'CREATE VIEW v AS SELECT id FROM t')

    def test_fresh_install_schema_has_eight_complete_triggers(self):
        schema = Path(__file__).parents[1] / 'database' / 'schema.mysql.sql'
        statements = parse_mysql_script(schema.read_text(encoding='utf-8'))
        triggers = [statement for statement in statements if statement.upper().startswith('CREATE TRIGGER')]
        self.assertEqual(len(triggers), 8)
        self.assertTrue(all(statement.rstrip().endswith('END') for statement in triggers))

    def test_schema_and_phase_three_migration_include_routines(self):
        root = Path(__file__).parents[1]
        schema = parse_mysql_script((root / 'database' / 'schema.mysql.sql').read_text(encoding='utf-8'))
        migration = parse_mysql_script((root / 'database' / 'migrations' / '003_routines_transactions.sql').read_text(encoding='utf-8'))
        expected = {'assign_officer', 'close_case', 'transfer_officer_cases'}
        for statements in (schema, migration):
            procedures = {name for name in expected if any(s.lower().startswith(f'create procedure {name}(') for s in statements)}
            functions = [s for s in statements if s.lower().startswith('create function days_open(')]
            self.assertEqual(procedures, expected)
            self.assertEqual(len(functions), 1)

    def test_case_persons_schema_and_legacy_migration(self):
        root = Path(__file__).parents[1]
        schema = (root / 'database' / 'schema.mysql.sql').read_text(encoding='utf-8')
        migration = (root / 'database' / 'migrations' / '004_case_persons.sql').read_text(encoding='utf-8')
        for source in (schema, migration):
            self.assertIn("ENUM('suspect','witness','victim','person_of_interest')", source)
            self.assertIn('PRIMARY KEY (case_reference, person_id, role)', source)
            self.assertIn('REFERENCES cases(case_ref) ON DELETE CASCADE', source)
            self.assertIn('REFERENCES persons(id) ON DELETE CASCADE', source)
        self.assertIn('INSERT IGNORE INTO case_persons', migration)
        self.assertIn("'person_of_interest'", migration)

    def test_analytics_views_and_window_queries_are_documented_in_schema(self):
        root = Path(__file__).parents[1]
        schema = (root / 'database' / 'schema.mysql.sql').read_text(encoding='utf-8').lower()
        migration = (root / 'database' / 'migrations' / '005_analytics_views.sql').read_text(encoding='utf-8').lower()
        for view in ('officer_workload_view', 'repeat_persons_view', 'public_case_view'):
            self.assertIn(f'view {view}', schema)
            self.assertIn(f'view {view}', migration)
        self.assertIn('having count(distinct cp.case_reference)>1', schema)
        self.assertIn('sql security invoker', schema)
        self.assertIn('rank() over', (root / 'backend' / 'api.py').read_text(encoding='utf-8').lower())
        self.assertIn('lag(case_count) over', (root / 'backend' / 'api.py').read_text(encoding='utf-8').lower())

    def test_performance_indexes_are_in_schema_and_existing_database_migration(self):
        root = Path(__file__).parents[1]
        schema = (root / 'database' / 'schema.mysql.sql').read_text(encoding='utf-8')
        migration = (root / 'database' / 'migrations' / '006_performance_indexes.sql').read_text(encoding='utf-8')
        for name in ('idx_cases_status', 'idx_cases_category', 'idx_cases_location', 'idx_cases_status_category_opened', 'idx_persons_name', 'idx_sessions_user_id'):
            self.assertIn(name, schema)
        self.assertIn('information_schema.STATISTICS', migration)
        for name in ('idx_cases_location', 'idx_cases_status_category_opened', 'idx_persons_name', 'idx_sessions_user_id'):
            self.assertIn(name, migration)
        explain = (root / 'scripts' / 'explain_compare.sql').read_text(encoding='utf-8')
        self.assertEqual(sum(line.strip() == 'EXPLAIN ANALYZE' for line in explain.splitlines()), 6)

    def test_evidence_schema_and_migration_enforce_append_only_history(self):
        root = Path(__file__).parents[1]
        schema = (root / 'database' / 'schema.mysql.sql').read_text(encoding='utf-8').lower()
        migration_source = (root / 'database' / 'migrations' / '007_evidence_custody.sql').read_text(encoding='utf-8')
        migration = parse_mysql_script(migration_source)
        for field in ('case_reference', 'description', '`type`', 'hash', 'storage_path', 'collected_by', 'collected_at'):
            self.assertIn(field, schema)
            self.assertIn(field, migration_source.lower())
        self.assertTrue(any(s.lower().startswith('create trigger custody_log_no_update') for s in migration))
        self.assertTrue(any(s.lower().startswith('create trigger custody_log_no_delete') for s in migration))
        self.assertIn('on delete restrict', schema)

    def test_hearings_schema_and_migration(self):
        root = Path(__file__).parents[1]
        schema = (root / 'database' / 'schema.mysql.sql').read_text(encoding='utf-8').lower()
        migration = (root / 'database' / 'migrations' / '008_court_hearings.sql').read_text(encoding='utf-8').lower()
        for source in (schema, migration):
            for field in ('case_reference', 'court', 'hearing_date', 'status', 'outcome', 'notes'):
                self.assertIn(field, source)
            self.assertIn("enum('scheduled','completed','adjourned','cancelled')", source)
            self.assertIn('fk_hearings_case', source)
            self.assertIn('idx_hearings_date_status', source)


if __name__ == '__main__':
    unittest.main()
