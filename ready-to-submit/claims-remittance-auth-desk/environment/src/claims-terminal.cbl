       IDENTIFICATION DIVISION.
       PROGRAM-ID. CLAIMS-TERMINAL.
       AUTHOR. CLAIMS-SYSTEMS-GROUP.
       
       ENVIRONMENT DIVISION.
       CONFIGURATION SECTION.
       REPOSITORY.
       
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       
       01 WS-ARGUMENT-COUNT             PIC 9(4) COMP-5 VALUE 0.
       01 WS-COMMAND                    PIC X(12) VALUE SPACES.
       01 WS-REVISION-TEXT              PIC X(16) VALUE SPACES.
       01 WS-BILLED-TEXT                PIC X(16) VALUE SPACES.
       01 WS-PAY-TEXT                   PIC X(16) VALUE SPACES.
       01 WS-CLAW-TEXT                  PIC X(16) VALUE SPACES.
       01 WS-VALIDATION-CODE            PIC X(32) VALUE SPACES.
       01 WS-USAGE-VALID                PIC X VALUE "Y".
          88 USAGE-VALID                VALUE "Y".
          88 USAGE-INVALID              VALUE "N".
       01 WS-MUTATION                   PIC X VALUE "N".
          88 MUTATION-COMMAND           VALUE "Y".
       01 WS-TRANSACTION-DONE           PIC X VALUE "N".
          88 TRANSACTION-DONE           VALUE "Y".
       01 WS-SQL-FAILED                 PIC X VALUE "N".
          88 SQL-FAILED                 VALUE "Y".
       01 WS-RETRYABLE                  PIC X VALUE "N".
          88 RETRYABLE-ERROR            VALUE "Y".
       01 WS-REPLAYED                   PIC X VALUE "N".
          88 REQUEST-REPLAYED           VALUE "Y".
       01 WS-BUSINESS-FAILED            PIC X VALUE "N".
          88 BUSINESS-FAILED            VALUE "Y".
       01 WS-ATTEMPT                    PIC 9 VALUE 0.
       01 WS-EXIT-STATUS                PIC 9 VALUE 0.
       01 WS-BUSINESS-CODE              PIC X(24) VALUE SPACES.
       01 WS-PRIOR-STATE                PIC X(12) VALUE SPACES.
       01 WS-NEW-STATE                  PIC X(12) VALUE SPACES.
       01 WS-REMITTANCE-OUT             PIC X(32) VALUE "NONE".
       01 WS-RESPONSE-WORK              PIC X(500) VALUE SPACES.
       01 WS-FINGERPRINT-WORK           PIC X(240) VALUE SPACES.
       01 WS-AUDIT-LINE                 PIC X(500) VALUE SPACES.
       01 WS-STATUS-LINE                PIC X(500) VALUE SPACES.
       01 WS-INDEX                      PIC 9(4) COMP-5 VALUE 0.
       01 WS-CHAR                       PIC X VALUE SPACE.
       01 WS-ALLOWED                    PIC X VALUE "N".
       
       01 WS-REVISION-EDIT              PIC 9(6).
       01 WS-AUDIT-EDIT                 PIC 9(10).
       01 WS-MONEY-EDIT                 PIC 9(12).
       01 WS-PATIENT-EDIT               PIC 9(12).
       01 WS-PLAN-EDIT                  PIC 9(12).
       01 WS-BILLED-EDIT                PIC 9(12).
       01 WS-DEDUCT-EDIT                PIC 9(12).
       
       EXEC SQL BEGIN DECLARE SECTION END-EXEC.
       01 H-DBNAME                      PIC X(80) VALUE SPACES.
       01 H-USERNAME                    PIC X(40) VALUE SPACES.
       01 H-PASSWORD                    PIC X(40) VALUE SPACES.
       01 H-REQUEST                     PIC X(24) VALUE SPACES.
       01 H-COMMAND                     PIC X(12) VALUE SPACES.
       01 H-CLAIM                       PIC X(16) VALUE SPACES.
       01 H-POLICY                      PIC X(16) VALUE SPACES.
       01 H-REMITTANCE                  PIC X(24) VALUE SPACES.
       01 H-EXPECTED-REVISION           PIC S9(9) COMP-3 VALUE 0.
       01 H-CURRENT-REVISION            PIC S9(9) COMP-3 VALUE 0.
       01 H-NEW-REVISION                PIC S9(9) COMP-3 VALUE 0.
       01 H-STATE                       PIC X(12) VALUE SPACES.
       01 H-BILLED                      PIC S9(18) COMP-3 VALUE 0.
       01 H-PATIENT-PAID                PIC S9(18) COMP-3 VALUE 0.
       01 H-PLAN-PAID                   PIC S9(18) COMP-3 VALUE 0.
       01 H-REMAINING-DEDUCTIBLE        PIC S9(18) COMP-3 VALUE 0.
       01 H-POLICY-DEDUCTIBLE           PIC S9(18) COMP-3 VALUE 0.
       01 H-COINSURANCE-PCT             PIC S9(4) COMP-3 VALUE 0.
       01 H-STOP-LOSS                   PIC S9(18) COMP-3 VALUE 0.
       01 H-PAY-CENTS                   PIC S9(18) COMP-3 VALUE 0.
       01 H-CLAW-CENTS                  PIC S9(18) COMP-3 VALUE 0.
       01 H-REMAINING-BILLED            PIC S9(18) COMP-3 VALUE 0.
       01 H-DEDUCTIBLE-TAKE             PIC S9(18) COMP-3 VALUE 0.
       01 H-AFTER-DEDUCTIBLE            PIC S9(18) COMP-3 VALUE 0.
       01 H-PATIENT-COINS               PIC S9(18) COMP-3 VALUE 0.
       01 H-PLAN-SHARE                  PIC S9(18) COMP-3 VALUE 0.
       01 H-STOP-REMAINING              PIC S9(18) COMP-3 VALUE 0.
       01 H-PATIENT-PORTION             PIC S9(18) COMP-3 VALUE 0.
       01 H-NEW-PATIENT                 PIC S9(18) COMP-3 VALUE 0.
       01 H-NEW-PLAN                    PIC S9(18) COMP-3 VALUE 0.
       01 H-NEW-DEDUCTIBLE              PIC S9(18) COMP-3 VALUE 0.
       01 H-DISPLAY-PATIENT             PIC S9(18) COMP-3 VALUE 0.
       01 H-DISPLAY-PLAN                PIC S9(18) COMP-3 VALUE 0.
       01 H-REM-PLAN                    PIC S9(18) COMP-3 VALUE 0.
       01 H-REM-CLAWED                  PIC S9(18) COMP-3 VALUE 0.
       01 H-CLAWABLE                    PIC S9(18) COMP-3 VALUE 0.
       01 H-NEW-CLAWED                  PIC S9(18) COMP-3 VALUE 0.
       01 H-COUNT                       PIC S9(9) COMP-3 VALUE 0.
       01 H-LOCK-KEY                    PIC X(40) VALUE SPACES.
       01 H-FINGERPRINT                 PIC X(240) VALUE SPACES.
       01 H-STORED-FINGERPRINT          PIC X(240) VALUE SPACES.
       01 H-RESPONSE                    PIC X(500) VALUE SPACES.
       01 H-STORED-RESPONSE             PIC X(500) VALUE SPACES.
       01 H-AUDIT-SEQUENCE              PIC S9(18) COMP-3 VALUE 0.
       01 H-AUDIT-REQUEST               PIC X(24) VALUE SPACES.
       01 H-AUDIT-ACTION                PIC X(12) VALUE SPACES.
       01 H-AUDIT-PRIOR                 PIC X(12) VALUE SPACES.
       01 H-AUDIT-NEW                   PIC X(12) VALUE SPACES.
       01 H-AUDIT-REVISION              PIC S9(9) COMP-3 VALUE 0.
       EXEC SQL END DECLARE SECTION END-EXEC.
       
       EXEC SQL INCLUDE SQLCA END-EXEC.
       
       PROCEDURE DIVISION.
       
       MAIN.
           PERFORM INITIALIZE-RUNTIME
           PERFORM PARSE-COMMAND
           IF USAGE-INVALID
        PERFORM EMIT-USAGE-ERROR
        MOVE 2 TO RETURN-CODE
        GOBACK
           END-IF
       
           PERFORM CONNECT-DATABASE
           IF SQL-FAILED
        PERFORM EMIT-DATABASE-ERROR
        MOVE 3 TO RETURN-CODE
        GOBACK
           END-IF
       
           EVALUATE TRUE
        WHEN WS-COMMAND = "HEALTH"
            PERFORM PROCESS-HEALTH
        WHEN WS-COMMAND = "STATUS"
            PERFORM PROCESS-STATUS
        WHEN WS-COMMAND = "AUDIT"
            PERFORM PROCESS-AUDIT
        WHEN MUTATION-COMMAND
            PERFORM PROCESS-MUTATION
        WHEN OTHER
            SET USAGE-INVALID TO TRUE
            PERFORM EMIT-USAGE-ERROR
            MOVE 2 TO WS-EXIT-STATUS
           END-EVALUATE
       
           PERFORM DISCONNECT-DATABASE
           MOVE WS-EXIT-STATUS TO RETURN-CODE
           GOBACK.
       
       INITIALIZE-RUNTIME.
           INITIALIZE H-REQUEST H-COMMAND H-CLAIM H-POLICY
               H-REMITTANCE H-FINGERPRINT H-RESPONSE
               H-STORED-FINGERPRINT H-STORED-RESPONSE
           MOVE "N" TO WS-MUTATION WS-TRANSACTION-DONE WS-SQL-FAILED
                WS-RETRYABLE WS-REPLAYED WS-BUSINESS-FAILED
           MOVE 0 TO WS-EXIT-STATUS
           ACCEPT H-DBNAME FROM ENVIRONMENT "CLAIMS_DB"
           ACCEPT H-USERNAME FROM ENVIRONMENT "CLAIMS_DB_USER"
           ACCEPT H-PASSWORD FROM ENVIRONMENT "CLAIMS_DB_PASSWORD"
           IF H-DBNAME = SPACES
        MOVE "claims@database:5432" TO H-DBNAME
           END-IF
           IF H-USERNAME = SPACES
        MOVE "claims_app" TO H-USERNAME
           END-IF
           IF H-PASSWORD = SPACES
        MOVE "claims_local" TO H-PASSWORD
           END-IF.
       
       PARSE-COMMAND.
           ACCEPT WS-ARGUMENT-COUNT FROM ARGUMENT-NUMBER
           IF WS-ARGUMENT-COUNT < 1
        SET USAGE-INVALID TO TRUE
        EXIT PARAGRAPH
           END-IF
           ACCEPT WS-COMMAND FROM ARGUMENT-VALUE
           MOVE FUNCTION UPPER-CASE(FUNCTION TRIM(WS-COMMAND))
             TO WS-COMMAND
           MOVE WS-COMMAND TO H-COMMAND
       
           EVALUATE WS-COMMAND
        WHEN "HEALTH"
            IF WS-ARGUMENT-COUNT NOT = 1
                SET USAGE-INVALID TO TRUE
            END-IF
        WHEN "STATUS"
            IF WS-ARGUMENT-COUNT NOT = 2
                SET USAGE-INVALID TO TRUE
            ELSE
                ACCEPT H-CLAIM FROM ARGUMENT-VALUE
                PERFORM VALIDATE-CLAIM-ID
            END-IF
        WHEN "AUDIT"
            IF WS-ARGUMENT-COUNT NOT = 2
                SET USAGE-INVALID TO TRUE
            ELSE
                ACCEPT H-CLAIM FROM ARGUMENT-VALUE
                PERFORM VALIDATE-CLAIM-ID
            END-IF
        WHEN "OPEN"
            SET MUTATION-COMMAND TO TRUE
            IF WS-ARGUMENT-COUNT NOT = 5
                SET USAGE-INVALID TO TRUE
            ELSE
                ACCEPT H-REQUEST FROM ARGUMENT-VALUE
                ACCEPT H-CLAIM FROM ARGUMENT-VALUE
                ACCEPT H-POLICY FROM ARGUMENT-VALUE
                ACCEPT WS-BILLED-TEXT FROM ARGUMENT-VALUE
                PERFORM VALIDATE-OPEN-ARGUMENTS
            END-IF
        WHEN "AUTHORIZE"
            SET MUTATION-COMMAND TO TRUE
            IF WS-ARGUMENT-COUNT NOT = 6
                SET USAGE-INVALID TO TRUE
            ELSE
                ACCEPT H-REQUEST FROM ARGUMENT-VALUE
                ACCEPT H-CLAIM FROM ARGUMENT-VALUE
                ACCEPT WS-REVISION-TEXT FROM ARGUMENT-VALUE
                ACCEPT H-REMITTANCE FROM ARGUMENT-VALUE
                ACCEPT WS-PAY-TEXT FROM ARGUMENT-VALUE
                PERFORM VALIDATE-AUTHORIZE-ARGUMENTS
            END-IF
        WHEN "CLAWBACK"
            SET MUTATION-COMMAND TO TRUE
            IF WS-ARGUMENT-COUNT NOT = 6
                SET USAGE-INVALID TO TRUE
            ELSE
                ACCEPT H-REQUEST FROM ARGUMENT-VALUE
                ACCEPT H-CLAIM FROM ARGUMENT-VALUE
                ACCEPT WS-REVISION-TEXT FROM ARGUMENT-VALUE
                ACCEPT H-REMITTANCE FROM ARGUMENT-VALUE
                ACCEPT WS-CLAW-TEXT FROM ARGUMENT-VALUE
                PERFORM VALIDATE-CLAWBACK-ARGUMENTS
            END-IF
        WHEN "CLOSE"
            SET MUTATION-COMMAND TO TRUE
            IF WS-ARGUMENT-COUNT NOT = 4
                SET USAGE-INVALID TO TRUE
            ELSE
                ACCEPT H-REQUEST FROM ARGUMENT-VALUE
                ACCEPT H-CLAIM FROM ARGUMENT-VALUE
                ACCEPT WS-REVISION-TEXT FROM ARGUMENT-VALUE
                PERFORM VALIDATE-CLOSE-ARGUMENTS
            END-IF
        WHEN OTHER
            SET USAGE-INVALID TO TRUE
           END-EVALUATE
           IF USAGE-VALID AND MUTATION-COMMAND
        PERFORM BUILD-FINGERPRINT
           END-IF.
       
       BUILD-FINGERPRINT.
           MOVE SPACES TO WS-FINGERPRINT-WORK
           EVALUATE WS-COMMAND
        WHEN "OPEN"
            STRING FUNCTION TRIM(WS-COMMAND) "|"
                   FUNCTION TRIM(H-REQUEST) "|"
                   FUNCTION TRIM(H-CLAIM) "|"
                   FUNCTION TRIM(H-POLICY) "|"
                   FUNCTION TRIM(WS-BILLED-TEXT)
              INTO WS-FINGERPRINT-WORK
            END-STRING
        WHEN "AUTHORIZE"
            STRING FUNCTION TRIM(WS-COMMAND) "|"
                   FUNCTION TRIM(H-REQUEST) "|"
                   FUNCTION TRIM(H-CLAIM) "|"
                   FUNCTION TRIM(WS-REVISION-TEXT) "|"
                   FUNCTION TRIM(H-REMITTANCE) "|"
                   FUNCTION TRIM(WS-PAY-TEXT)
              INTO WS-FINGERPRINT-WORK
            END-STRING
        WHEN "CLAWBACK"
            STRING FUNCTION TRIM(WS-COMMAND) "|"
                   FUNCTION TRIM(H-REQUEST) "|"
                   FUNCTION TRIM(H-CLAIM) "|"
                   FUNCTION TRIM(WS-REVISION-TEXT) "|"
                   FUNCTION TRIM(H-REMITTANCE) "|"
                   FUNCTION TRIM(WS-CLAW-TEXT)
              INTO WS-FINGERPRINT-WORK
            END-STRING
        WHEN OTHER
            STRING FUNCTION TRIM(WS-COMMAND) "|"
                   FUNCTION TRIM(H-REQUEST) "|"
                   FUNCTION TRIM(H-CLAIM) "|"
                   FUNCTION TRIM(WS-REVISION-TEXT)
              INTO WS-FINGERPRINT-WORK
            END-STRING
           END-EVALUATE
           MOVE FUNCTION TRIM(WS-FINGERPRINT-WORK) TO H-FINGERPRINT.
       
       CONNECT-DATABASE.
           EXEC SQL
        CONNECT :H-USERNAME IDENTIFIED BY :H-PASSWORD
          USING :H-DBNAME
           END-EXEC
           IF SQLCODE NOT = 0
        SET SQL-FAILED TO TRUE
           END-IF.
       
       DISCONNECT-DATABASE.
           EXEC SQL ROLLBACK END-EXEC
           EXEC SQL DISCONNECT ALL END-EXEC.
       
       PROCESS-HEALTH.
           MOVE 0 TO H-COUNT
           EXEC SQL
        SELECT COUNT(*) INTO :H-COUNT
          FROM information_schema.tables
         WHERE table_schema = 'public'
           AND table_name IN
               ('claim', 'remittance', 'request_record',
                'audit_event')
           END-EXEC
           IF SQLCODE = 0 AND H-COUNT = 4
        DISPLAY "HEALTH|database=READY|schema=1"
        MOVE 0 TO WS-EXIT-STATUS
           ELSE
        DISPLAY "ERR|request=NONE|command=HEALTH|"
                "code=DATABASE_ERROR"
            UPON STDERR
        MOVE 3 TO WS-EXIT-STATUS
           END-IF.
       
       PROCESS-STATUS.
           MOVE 0 TO H-COUNT
           EXEC SQL
        SELECT COUNT(*) INTO :H-COUNT
          FROM claim
         WHERE claim_id = :H-CLAIM
           END-EXEC
           IF SQLCODE NOT = 0
        PERFORM EMIT-DATABASE-ERROR
        MOVE 3 TO WS-EXIT-STATUS
        EXIT PARAGRAPH
           END-IF
           IF H-COUNT = 0
        DISPLAY "ERR|request=NONE|command=STATUS|"
                "code=UNKNOWN_CLAIM"
        MOVE 1 TO WS-EXIT-STATUS
        EXIT PARAGRAPH
           END-IF
       
           EXEC SQL
        SELECT policy_id, revision, state, billed_cents,
               patient_paid, plan_paid, remaining_deductible
          INTO :H-POLICY, :H-CURRENT-REVISION, :H-STATE,
               :H-BILLED, :H-PATIENT-PAID, :H-PLAN-PAID,
               :H-REMAINING-DEDUCTIBLE
          FROM claim
         WHERE claim_id = :H-CLAIM
           END-EXEC
           IF SQLCODE NOT = 0
        PERFORM EMIT-DATABASE-ERROR
        MOVE 3 TO WS-EXIT-STATUS
        EXIT PARAGRAPH
           END-IF
           MOVE H-CURRENT-REVISION TO WS-REVISION-EDIT
           MOVE H-BILLED TO WS-BILLED-EDIT
           MOVE H-PATIENT-PAID TO WS-PATIENT-EDIT
           MOVE H-PLAN-PAID TO WS-PLAN-EDIT
           MOVE H-REMAINING-DEDUCTIBLE TO WS-DEDUCT-EDIT
           MOVE SPACES TO WS-STATUS-LINE
           STRING "STATUS|claim=" FUNCTION TRIM(H-CLAIM)
           "|policy=" FUNCTION TRIM(H-POLICY)
           "|revision=" WS-REVISION-EDIT
           "|state=" FUNCTION TRIM(H-STATE)
           "|billed=" WS-BILLED-EDIT
           "|patient=" WS-PATIENT-EDIT
           "|plan=" WS-PLAN-EDIT
           "|deductible=" WS-DEDUCT-EDIT
             INTO WS-STATUS-LINE
           END-STRING
           DISPLAY FUNCTION TRIM(WS-STATUS-LINE TRAILING)
           MOVE 0 TO WS-EXIT-STATUS.
       
       PROCESS-AUDIT.
           EXEC SQL
               DECLARE AUDITCURSOR CURSOR FOR
               SELECT audit_sequence,
                      request_id,
                      action,
                      prior_state,
                      new_state,
                      resulting_revision
                 FROM audit_event
                WHERE claim_id = :H-CLAIM
                ORDER BY audit_sequence
           END-EXEC
           MOVE 0 TO H-COUNT
           EXEC SQL
        SELECT COUNT(*) INTO :H-COUNT
          FROM claim
         WHERE claim_id = :H-CLAIM
           END-EXEC
           IF SQLCODE NOT = 0
        PERFORM EMIT-DATABASE-ERROR
        MOVE 3 TO WS-EXIT-STATUS
        EXIT PARAGRAPH
           END-IF
           IF H-COUNT = 0
        DISPLAY "ERR|request=NONE|command=AUDIT|"
                "code=UNKNOWN_CLAIM"
        MOVE 1 TO WS-EXIT-STATUS
        EXIT PARAGRAPH
           END-IF
       
           EXEC SQL OPEN AUDITCURSOR END-EXEC
           IF SQLCODE NOT = 0
        PERFORM EMIT-DATABASE-ERROR
        MOVE 3 TO WS-EXIT-STATUS
        EXIT PARAGRAPH
           END-IF
           PERFORM WITH TEST AFTER UNTIL SQLCODE NOT = 0
        EXEC SQL
                   FETCH AUDITCURSOR
             INTO :H-AUDIT-SEQUENCE,
                  :H-AUDIT-REQUEST,
                  :H-AUDIT-ACTION,
                  :H-AUDIT-PRIOR,
                  :H-AUDIT-NEW,
                  :H-AUDIT-REVISION
        END-EXEC
        IF SQLCODE = 0
            MOVE H-AUDIT-SEQUENCE TO WS-AUDIT-EDIT
            MOVE H-AUDIT-REVISION TO WS-REVISION-EDIT
            MOVE SPACES TO WS-AUDIT-LINE
            STRING "AUDIT|sequence=" WS-AUDIT-EDIT
                   "|request=" FUNCTION TRIM(H-AUDIT-REQUEST)
                   "|claim=" FUNCTION TRIM(H-CLAIM)
                   "|action=" FUNCTION TRIM(H-AUDIT-ACTION)
                   "|from=" FUNCTION TRIM(H-AUDIT-PRIOR)
                   "|to=" FUNCTION TRIM(H-AUDIT-NEW)
                   "|revision=" WS-REVISION-EDIT
              INTO WS-AUDIT-LINE
            END-STRING
            DISPLAY FUNCTION TRIM(WS-AUDIT-LINE TRAILING)
        END-IF
           END-PERFORM
           EXEC SQL CLOSE AUDITCURSOR END-EXEC
           MOVE 0 TO WS-EXIT-STATUS.
       
       PROCESS-MUTATION.
           MOVE "N" TO WS-TRANSACTION-DONE
           PERFORM VARYING WS-ATTEMPT FROM 1 BY 1
        UNTIL TRANSACTION-DONE OR WS-ATTEMPT > 8
        MOVE "N" TO WS-SQL-FAILED WS-RETRYABLE
        PERFORM TRANSACTION-ATTEMPT
        IF SQL-FAILED
            IF SQLSTATE = "40001" OR SQLSTATE = "40P01"
                SET RETRYABLE-ERROR TO TRUE
            END-IF
            EXEC SQL ROLLBACK END-EXEC
            IF NOT RETRYABLE-ERROR
                SET TRANSACTION-DONE TO TRUE
                MOVE 3 TO WS-EXIT-STATUS
                PERFORM EMIT-DATABASE-ERROR
            END-IF
        END-IF
           END-PERFORM
           IF NOT TRANSACTION-DONE
        DISPLAY "ERR|request=" FUNCTION TRIM(H-REQUEST)
                "|command=" FUNCTION TRIM(H-COMMAND)
                "|code=RETRY_EXHAUSTED" UPON STDERR
        MOVE 3 TO WS-EXIT-STATUS
           END-IF.
       
       TRANSACTION-ATTEMPT.
           EXEC SQL INCLUDE "transaction-begin" END-EXEC.
           IF SQL-FAILED
        EXIT PARAGRAPH
           END-IF
       
           PERFORM HANDLE-REQUEST-IDENTITY
           IF SQL-FAILED
        EXIT PARAGRAPH
           END-IF
           IF REQUEST-REPLAYED
        EXEC SQL COMMIT END-EXEC
        IF SQLCODE NOT = 0
            SET SQL-FAILED TO TRUE
            EXIT PARAGRAPH
        END-IF
        DISPLAY FUNCTION TRIM(H-STORED-RESPONSE TRAILING)
        MOVE 0 TO WS-EXIT-STATUS
        SET TRANSACTION-DONE TO TRUE
        EXIT PARAGRAPH
           END-IF
           IF BUSINESS-FAILED
        EXEC SQL ROLLBACK END-EXEC
        DISPLAY FUNCTION TRIM(H-RESPONSE TRAILING)
        MOVE 1 TO WS-EXIT-STATUS
        SET TRANSACTION-DONE TO TRUE
        EXIT PARAGRAPH
           END-IF
       
           EVALUATE WS-COMMAND
        WHEN "OPEN"
            PERFORM APPLY-OPEN
        WHEN "AUTHORIZE"
            PERFORM APPLY-AUTHORIZE
        WHEN "CLAWBACK"
            PERFORM APPLY-CLAWBACK
        WHEN "CLOSE"
            PERFORM APPLY-CLOSE
           END-EVALUATE
           IF SQL-FAILED
        EXIT PARAGRAPH
           END-IF
       
           IF BUSINESS-FAILED
        PERFORM RECORD-BUSINESS-REJECTION
           ELSE
        PERFORM RECORD-ACCEPTED-TRANSACTION
           END-IF
           IF SQL-FAILED
        EXIT PARAGRAPH
           END-IF
       
           EXEC SQL COMMIT END-EXEC
           IF SQLCODE NOT = 0
        SET SQL-FAILED TO TRUE
        EXIT PARAGRAPH
           END-IF
           DISPLAY FUNCTION TRIM(H-RESPONSE TRAILING)
           IF BUSINESS-FAILED
        MOVE 1 TO WS-EXIT-STATUS
           ELSE
        MOVE 0 TO WS-EXIT-STATUS
           END-IF
           SET TRANSACTION-DONE TO TRUE.
       
       HANDLE-REQUEST-IDENTITY.
           MOVE "N" TO WS-REPLAYED WS-BUSINESS-FAILED
           EXEC SQL INCLUDE "request-identity" END-EXEC.
       
       APPLY-OPEN.
           MOVE 0 TO H-COUNT
           EXEC SQL
        SELECT COUNT(*) INTO :H-COUNT
          FROM claim
         WHERE claim_id = :H-CLAIM
           END-EXEC
           IF SQLCODE NOT = 0
        SET SQL-FAILED TO TRUE
        EXIT PARAGRAPH
           END-IF
           IF H-COUNT > 0
        PERFORM SET-CLAIM-EXISTS
        EXIT PARAGRAPH
           END-IF
       
           MOVE 0 TO H-COUNT
           EXEC SQL
        SELECT COUNT(*) INTO :H-COUNT
          FROM policy
         WHERE policy_id = :H-POLICY
           END-EXEC
           IF SQLCODE NOT = 0
        SET SQL-FAILED TO TRUE
        EXIT PARAGRAPH
           END-IF
           IF H-COUNT = 0
        PERFORM SET-UNKNOWN-POLICY
        EXIT PARAGRAPH
           END-IF
       
           EXEC SQL
        SELECT deductible_cents
          INTO :H-POLICY-DEDUCTIBLE
          FROM policy
         WHERE policy_id = :H-POLICY
           END-EXEC
           IF SQLCODE NOT = 0
        SET SQL-FAILED TO TRUE
        EXIT PARAGRAPH
           END-IF
       
           EXEC SQL
        INSERT INTO claim
            (claim_id, policy_id, billed_cents, patient_paid,
             plan_paid, remaining_deductible, revision, state)
        VALUES
            (:H-CLAIM, :H-POLICY, :H-BILLED, 0, 0,
             :H-POLICY-DEDUCTIBLE, 1, 'OPEN')
           END-EXEC
           IF SQLCODE NOT = 0
        SET SQL-FAILED TO TRUE
        EXIT PARAGRAPH
           END-IF
           MOVE 1 TO H-NEW-REVISION
           MOVE 0 TO H-NEW-PATIENT H-NEW-PLAN
           MOVE "NONE" TO WS-PRIOR-STATE
           MOVE "OPEN" TO WS-NEW-STATE
           MOVE "NONE" TO WS-REMITTANCE-OUT.
       
       APPLY-AUTHORIZE.
           PERFORM LOAD-CLAIM-FOR-UPDATE
           IF SQL-FAILED OR BUSINESS-FAILED
        EXIT PARAGRAPH
           END-IF
           IF H-EXPECTED-REVISION NOT = H-CURRENT-REVISION
        PERFORM SET-STALE-REVISION
        EXIT PARAGRAPH
           END-IF
           IF FUNCTION TRIM(H-STATE) NOT = "OPEN"
       AND FUNCTION TRIM(H-STATE) NOT = "ACTIVE"
        PERFORM SET-INVALID-STATE
        EXIT PARAGRAPH
           END-IF
       
           MOVE SPACES TO H-LOCK-KEY
           STRING "REMITTANCE:" FUNCTION TRIM(H-REMITTANCE)
             INTO H-LOCK-KEY
           END-STRING
           EXEC SQL
           SELECT COUNT(*) INTO :H-COUNT
             FROM pg_advisory_xact_lock(
                  hashtext(:H-LOCK-KEY))
           END-EXEC
           IF SQLCODE NOT = 0
        SET SQL-FAILED TO TRUE
        EXIT PARAGRAPH
           END-IF
       
           MOVE 0 TO H-COUNT
           EXEC SQL
        SELECT COUNT(*) INTO :H-COUNT
          FROM remittance
         WHERE remittance_id = :H-REMITTANCE
           END-EXEC
           IF SQLCODE NOT = 0
        SET SQL-FAILED TO TRUE
        EXIT PARAGRAPH
           END-IF
           IF H-COUNT > 0
        PERFORM SET-REMITTANCE-EXISTS
        EXIT PARAGRAPH
           END-IF
       
           EXEC SQL
        SELECT deductible_cents, coinsurance_pct, stop_loss_cents
          INTO :H-POLICY-DEDUCTIBLE, :H-COINSURANCE-PCT,
               :H-STOP-LOSS
          FROM policy
         WHERE policy_id = :H-POLICY
           END-EXEC
           IF SQLCODE NOT = 0
        SET SQL-FAILED TO TRUE
        EXIT PARAGRAPH
           END-IF
       
           EXEC SQL INCLUDE "deductible-math" END-EXEC.
           IF BUSINESS-FAILED OR SQL-FAILED
        EXIT PARAGRAPH
           END-IF
       
           COMPUTE H-NEW-REVISION = H-CURRENT-REVISION + 1
           IF FUNCTION TRIM(H-STATE) = "OPEN"
        MOVE "OPEN" TO WS-PRIOR-STATE
        MOVE "ACTIVE" TO WS-NEW-STATE
           ELSE
        MOVE "ACTIVE" TO WS-PRIOR-STATE WS-NEW-STATE
           END-IF
       
           EXEC SQL
        INSERT INTO remittance
            (remittance_id, claim_id, request_id, charge_cents,
             plan_cents, patient_cents, deductible_applied,
             clawed_cents)
        VALUES
            (:H-REMITTANCE, :H-CLAIM, :H-REQUEST, :H-PAY-CENTS,
             :H-PLAN-SHARE, :H-PATIENT-PORTION,
             :H-DEDUCTIBLE-TAKE, 0)
           END-EXEC
           IF SQLCODE NOT = 0
        SET SQL-FAILED TO TRUE
        EXIT PARAGRAPH
           END-IF
       
           EXEC SQL
        UPDATE claim
           SET patient_paid = :H-NEW-PATIENT,
               plan_paid = :H-NEW-PLAN,
               remaining_deductible = :H-NEW-DEDUCTIBLE,
               revision = :H-NEW-REVISION,
               state = 'ACTIVE'
         WHERE claim_id = :H-CLAIM
           END-EXEC
           IF SQLCODE NOT = 0
        SET SQL-FAILED TO TRUE
        EXIT PARAGRAPH
           END-IF
           MOVE H-REMITTANCE TO WS-REMITTANCE-OUT.
       
       APPLY-CLAWBACK.
           PERFORM LOAD-CLAIM-FOR-UPDATE
           IF SQL-FAILED OR BUSINESS-FAILED
        EXIT PARAGRAPH
           END-IF
           IF H-EXPECTED-REVISION NOT = H-CURRENT-REVISION
        PERFORM SET-STALE-REVISION
        EXIT PARAGRAPH
           END-IF
           IF FUNCTION TRIM(H-STATE) NOT = "ACTIVE"
        PERFORM SET-INVALID-STATE
        EXIT PARAGRAPH
           END-IF
           EXEC SQL INCLUDE "clawback-order" END-EXEC.
       
       APPLY-CLOSE.
           PERFORM LOAD-CLAIM-FOR-UPDATE
           IF SQL-FAILED OR BUSINESS-FAILED
        EXIT PARAGRAPH
           END-IF
           IF H-EXPECTED-REVISION NOT = H-CURRENT-REVISION
        PERFORM SET-STALE-REVISION
        EXIT PARAGRAPH
           END-IF
           IF FUNCTION TRIM(H-STATE) NOT = "OPEN"
       AND FUNCTION TRIM(H-STATE) NOT = "ACTIVE"
        PERFORM SET-INVALID-STATE
        EXIT PARAGRAPH
           END-IF
           MOVE H-STATE TO WS-PRIOR-STATE
           MOVE "CLOSED" TO WS-NEW-STATE
           COMPUTE H-NEW-REVISION = H-CURRENT-REVISION + 1
           MOVE H-PATIENT-PAID TO H-NEW-PATIENT
           MOVE H-PLAN-PAID TO H-NEW-PLAN
           EXEC SQL
        UPDATE claim
           SET state = 'CLOSED', revision = :H-NEW-REVISION
         WHERE claim_id = :H-CLAIM
           END-EXEC
           IF SQLCODE NOT = 0
        SET SQL-FAILED TO TRUE
        EXIT PARAGRAPH
           END-IF
           MOVE "NONE" TO WS-REMITTANCE-OUT.
       
       LOAD-CLAIM-FOR-UPDATE.
           MOVE 0 TO H-COUNT
           EXEC SQL
        SELECT COUNT(*) INTO :H-COUNT
          FROM claim
         WHERE claim_id = :H-CLAIM
           END-EXEC
           IF SQLCODE NOT = 0
        SET SQL-FAILED TO TRUE
        EXIT PARAGRAPH
           END-IF
           IF H-COUNT = 0
        PERFORM SET-UNKNOWN-CLAIM
        EXIT PARAGRAPH
           END-IF
           EXEC SQL
        SELECT policy_id, revision, state, billed_cents,
               patient_paid, plan_paid, remaining_deductible
          INTO :H-POLICY, :H-CURRENT-REVISION, :H-STATE,
               :H-BILLED, :H-PATIENT-PAID, :H-PLAN-PAID,
               :H-REMAINING-DEDUCTIBLE
          FROM claim
         WHERE claim_id = :H-CLAIM
           FOR UPDATE
           END-EXEC
           IF SQLCODE NOT = 0
        SET SQL-FAILED TO TRUE
           END-IF.
       
       RECORD-BUSINESS-REJECTION.
           EXEC SQL INCLUDE "audit-reserve" END-EXEC.
           IF SQL-FAILED
        EXIT PARAGRAPH
           END-IF
           PERFORM BUILD-ERROR-RESPONSE
           EXEC SQL
        INSERT INTO request_record
            (request_id, command_name, fingerprint,
             response_line, claim_id)
        VALUES
            (:H-REQUEST, :H-COMMAND, :H-FINGERPRINT, :H-RESPONSE,
             :H-CLAIM)
           END-EXEC
           IF SQLCODE NOT = 0
        SET SQL-FAILED TO TRUE
           END-IF.
       
       RECORD-ACCEPTED-TRANSACTION.
           EXEC SQL INCLUDE "audit-reserve" END-EXEC.
           IF SQL-FAILED
        EXIT PARAGRAPH
           END-IF
           PERFORM BUILD-SUCCESS-RESPONSE
           EXEC SQL
        INSERT INTO request_record
            (request_id, command_name, fingerprint,
             response_line, claim_id)
        VALUES
            (:H-REQUEST, :H-COMMAND, :H-FINGERPRINT, :H-RESPONSE,
             :H-CLAIM)
           END-EXEC
           IF SQLCODE NOT = 0
        SET SQL-FAILED TO TRUE
        EXIT PARAGRAPH
           END-IF
           EXEC SQL
        INSERT INTO audit_event
            (audit_sequence, request_id, claim_id, action,
             prior_state, new_state, resulting_revision)
        VALUES
            (:H-AUDIT-SEQUENCE, :H-REQUEST, :H-CLAIM, :H-COMMAND,
             :WS-PRIOR-STATE, :WS-NEW-STATE, :H-NEW-REVISION)
           END-EXEC
           IF SQLCODE NOT = 0
        SET SQL-FAILED TO TRUE
           END-IF.
       
       BUILD-SUCCESS-RESPONSE.
           MOVE H-NEW-REVISION TO WS-REVISION-EDIT
           MOVE H-AUDIT-SEQUENCE TO WS-AUDIT-EDIT
           MOVE H-NEW-PATIENT TO WS-PATIENT-EDIT
           MOVE H-NEW-PLAN TO WS-PLAN-EDIT
           MOVE SPACES TO WS-RESPONSE-WORK H-RESPONSE
           STRING "OK|request=" FUNCTION TRIM(H-REQUEST)
           "|command=" FUNCTION TRIM(H-COMMAND)
           "|claim=" FUNCTION TRIM(H-CLAIM)
           "|remittance=" FUNCTION TRIM(WS-REMITTANCE-OUT)
           "|revision=" WS-REVISION-EDIT
           "|state=" FUNCTION TRIM(WS-NEW-STATE)
           "|patient=" WS-PATIENT-EDIT
           "|plan=" WS-PLAN-EDIT
           "|audit=" WS-AUDIT-EDIT
             INTO WS-RESPONSE-WORK
           END-STRING
           MOVE FUNCTION TRIM(WS-RESPONSE-WORK) TO H-RESPONSE.
       
       BUILD-ERROR-RESPONSE.
           MOVE SPACES TO WS-RESPONSE-WORK H-RESPONSE
           STRING "ERR|request=" FUNCTION TRIM(H-REQUEST)
           "|command=" FUNCTION TRIM(H-COMMAND)
           "|code=" FUNCTION TRIM(WS-BUSINESS-CODE)
             INTO WS-RESPONSE-WORK
           END-STRING
           MOVE FUNCTION TRIM(WS-RESPONSE-WORK) TO H-RESPONSE.
       
       SET-CLAIM-EXISTS.
           SET BUSINESS-FAILED TO TRUE
           MOVE "CLAIM_EXISTS" TO WS-BUSINESS-CODE.
       
       SET-UNKNOWN-CLAIM.
           SET BUSINESS-FAILED TO TRUE
           MOVE "UNKNOWN_CLAIM" TO WS-BUSINESS-CODE.
       
       SET-UNKNOWN-POLICY.
           SET BUSINESS-FAILED TO TRUE
           MOVE "UNKNOWN_POLICY" TO WS-BUSINESS-CODE.
       
       SET-STALE-REVISION.
           SET BUSINESS-FAILED TO TRUE
           MOVE "STALE_REVISION" TO WS-BUSINESS-CODE.
       
       SET-INVALID-STATE.
           SET BUSINESS-FAILED TO TRUE
           MOVE "INVALID_STATE" TO WS-BUSINESS-CODE.
       
       SET-REMITTANCE-EXISTS.
           SET BUSINESS-FAILED TO TRUE
           MOVE "REMITTANCE_EXISTS" TO WS-BUSINESS-CODE.
       
       SET-UNKNOWN-REMITTANCE.
           SET BUSINESS-FAILED TO TRUE
           MOVE "UNKNOWN_REMITTANCE" TO WS-BUSINESS-CODE.
       
       SET-EXCEEDS-BILLED.
           SET BUSINESS-FAILED TO TRUE
           MOVE "EXCEEDS_BILLED" TO WS-BUSINESS-CODE.
       
       SET-EXCEEDS-STOP-LOSS.
           SET BUSINESS-FAILED TO TRUE
           MOVE "EXCEEDS_STOP_LOSS" TO WS-BUSINESS-CODE.
       
       SET-EXCEEDS-CLAWBACK.
           SET BUSINESS-FAILED TO TRUE
           MOVE "EXCEEDS_CLAWBACK" TO WS-BUSINESS-CODE.
       
       SET-REQUEST-CONFLICT.
           SET BUSINESS-FAILED TO TRUE
           MOVE "REQUEST_CONFLICT" TO WS-BUSINESS-CODE
           PERFORM BUILD-ERROR-RESPONSE.
       
       EMIT-USAGE-ERROR.
           DISPLAY "ERR|request=NONE|command=" FUNCTION TRIM(WS-COMMAND)
            "|code=USAGE" UPON STDERR.
       
       EMIT-DATABASE-ERROR.
           DISPLAY "ERR|request=" FUNCTION TRIM(H-REQUEST)
            "|command=" FUNCTION TRIM(H-COMMAND)
            "|code=DATABASE_ERROR" UPON STDERR.
       
       COPY "validation-rules.cpy".
       
       END PROGRAM CLAIMS-TERMINAL.
