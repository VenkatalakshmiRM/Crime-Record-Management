USE casework;

CREATE TABLE IF NOT EXISTS hearings (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  case_reference VARCHAR(80) NOT NULL,
  court VARCHAR(240) NOT NULL,
  hearing_date DATE NOT NULL,
  status ENUM('Scheduled','Completed','Adjourned','Cancelled') NOT NULL,
  outcome TEXT NULL,
  notes TEXT NULL,
  INDEX idx_hearings_case(case_reference,hearing_date),
  INDEX idx_hearings_date_status(hearing_date,status),
  CONSTRAINT fk_hearings_case FOREIGN KEY(case_reference) REFERENCES cases(case_ref) ON DELETE RESTRICT
) ENGINE=InnoDB;
