# Database normalization

## First normal form (1NF)

Each `case_persons` row stores one atomic relationship: one case, one person, one role, and one link timestamp. A person linked to several cases has several rows instead of a list of references in one field. A person can hold more than one role for a case because the relationship key includes the role.

## Second normal form (2NF)

The composite primary key is `(case_reference, person_id, role)`. `added_at` describes that complete relationship and depends on the full key. Case titles and status depend on the case; person names and charges depend on the person. None of those entity attributes are copied into the junction table, which avoids partial dependencies and repeated facts.

## Third normal form (3NF)

The junction contains only relationship identifiers and relationship attributes. Case details remain in `cases`, and person details remain in `persons`; attributes that depend on those entities are not transitively stored in the link table. The role column is constrained to the supported domain: `suspect`, `witness`, `victim`, or `person_of_interest`.

## Compatibility during migration

`persons.case_id` remains as a deprecated compatibility pointer for existing clients and older data. On startup, each existing pointer is copied idempotently to `case_persons` with role `person_of_interest`; the source column is retained, so the migration does not discard data. New clients use the `cases` array in person API responses and send `cases: [{"case_reference": "...", "role": "suspect"}]` when creating or replacing links. Existing clients can continue to send the original single `case` string. That legacy write keeps the previous single-link behavior. When a person has several links, the legacy `case` response field points to the compatibility link, or the first canonical link if the person has no legacy pointer.
