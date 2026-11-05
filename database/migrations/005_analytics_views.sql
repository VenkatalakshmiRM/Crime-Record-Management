USE casework;

CREATE OR REPLACE VIEW case_view AS
SELECT c.id,c.case_ref,c.title,c.category,c.status,c.officer_id,o.name AS officer_name,
       c.opened_on,c.location,c.resolution,c.created_at,c.updated_at
FROM cases c LEFT JOIN officers o ON o.id=c.officer_id;

CREATE OR REPLACE VIEW officer_workload_view AS
SELECT o.id AS officer_id,o.name AS officer_name,o.role,o.badge,
       COUNT(c.id) AS total_cases,
       COALESCE(SUM(CASE WHEN c.status='Closed' THEN 1 ELSE 0 END),0) AS closed_cases,
       COALESCE(SUM(CASE WHEN c.id IS NOT NULL AND c.status<>'Closed' THEN 1 ELSE 0 END),0) AS open_cases
FROM officers o LEFT JOIN cases c ON c.officer_id=o.id
GROUP BY o.id,o.name,o.role,o.badge;
