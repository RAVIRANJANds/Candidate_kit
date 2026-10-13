# DECISIONS.md

1. **Indexes.** I added a unique index on `employees.emp_code` and on `attendance_logs (emp_code, date)` so duplicate punch-ins fail at the database. Listing uses `(date desc, emp_code)`; punch-out lookup uses `(emp_code, punch_in desc)`. I skipped a text index on `name` because nothing searches by name.

2. **Punch-in race.** Both requests hit `insert_one` with the same key. One insert wins; the other gets `DuplicateKeyError` and returns 409. No separate “check then insert”.

3. **Ties.** Leaderboard uses competition ranking: tied `total_late_minutes` share a rank and the next rank is skipped. With `limit=10`, everyone with `rank <= 10` is returned, so you can get more than ten rows when many people tie at rank 10.

4. **Headcount.** Department summary starts from `employees` with `joined_on <= month end`, groups by department for headcount, then `$lookup` logs. People with zero logs still sit in the employee group, so they count in headcount even if all log sums are zero.

5. **At 100x scale.** I would move department daily trend gap-filling fully into MongoDB (`$densify` + windowed averages) and shard `attendance_logs` by `date`, keeping hot indexes on the natural keys only.
