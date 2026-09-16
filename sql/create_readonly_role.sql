-- Read-only login for the Text-to-SQL agent. The app must never connect with
-- the admin credentials used to create the schema/load data.
--
-- Use scripts/create_readonly_login.py instead of running this file directly
-- — sqlcmd (needed for the $(LoginPassword) substitution below) isn't
-- installed in our app container. This file is kept as a plain-SQL reference
-- for anyone running it manually via Azure Data Studio / the Azure portal
-- query editor, which don't have that limitation.
--
-- Run against master first to create the login (substitute a real password),
-- then against the target database to create the user and grant db_datareader:
--   CREATE LOGIN app_readonly WITH PASSWORD = '<pick one>';   -- run against master
--   CREATE USER app_readonly FROM LOGIN app_readonly;         -- run against the target database
--   ALTER ROLE db_datareader ADD MEMBER app_readonly;         -- run against the target database

CREATE LOGIN app_readonly WITH PASSWORD = '<pick one>';
