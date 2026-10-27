USE casework;

CREATE TABLE IF NOT EXISTS case_persons (
  case_reference VARCHAR(80) NOT NULL,
  person_id BIGINT UNSIGNED NOT NULL,
  role ENUM('suspect','witness','victim','person_of_interest') NOT NULL,
  added_at VARCHAR(40) NOT NULL,
  PRIMARY KEY (case_reference, person_id, role),
  INDEX idx_case_persons_person(person_id,case_reference),
  CONSTRAINT fk_case_persons_case FOREIGN KEY(case_reference) REFERENCES cases(case_ref) ON DELETE CASCADE,
  CONSTRAINT fk_case_persons_person FOREIGN KEY(person_id) REFERENCES persons(id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- Preserve every existing single-case link as a person_of_interest relationship.
-- INSERT IGNORE makes this data migration safe to run again.
INSERT IGNORE INTO case_persons(case_reference,person_id,role,added_at)
SELECT c.case_ref,p.id,'person_of_interest',COALESCE(p.created_at,UTC_TIMESTAMP())
FROM persons p
JOIN cases c ON c.id=p.case_id
WHERE p.case_id IS NOT NULL;
