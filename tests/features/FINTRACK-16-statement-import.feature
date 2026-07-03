# FINTRACK-16: Statement/CSV/PDF Import — 5pts (Jira key; drafted locally as FINTRACK-005)
# As a privacy-first user, I want to upload a bank/card statement file, so that I can bulk-import
# transaction history without connecting my bank account.
# AC: CSV/PDF/XLSX upload | parses date/amount/description columns | review screen before commit
#     ("X found, Y flagged") | bulk-edit before commit | reviewed rows use same CreateTransactionCommand
#     as manual entry (entry_source: csv_import) | corrupted file = clear error, not silent partial import
#     | no bank credentials ever requested
# Out of scope: live bank sync (P2), OFX/QFX formats, automatic recurring re-import

Feature: Statement Import

  Scenario: Successfully import a CSV statement
    Given I have a CSV file with 50 well-formed transactions
    When I upload the file
    Then I should see a review screen showing "50 transactions found"
    And I should be able to confirm and commit all 50 transactions

  Scenario: Upload a corrupted or unparseable file
    Given I have a corrupted CSV file
    When I upload the file
    Then I should see a clear error "Could not read this file"
    And no transactions should be imported

  Scenario: File contains zero valid transactions
    Given I upload a CSV file with a header row but no data rows
    Then I should see "0 transactions found"
    And I should not be able to commit an empty import

  Scenario: Attempt CSV formula injection via a transaction description
    Given I have a CSV file where a description cell contains "=cmd|'/c calc'!A1"
    When I upload and review the file
    Then the cell should be treated as inert text, never evaluated as a formula
    And I should see validation warning "Suspicious content sanitised in row 1"
    And a security event should be logged
