       01  INPUT-RECORD                 PIC X(512).
       01  OUTPUT-RECORD                PIC X(512).
       01  STOCK-OUTPUT-RECORD.
           05 SO-DEPOT                  PIC X(6).
           05 SO-PART                   PIC X(10).
           05 SO-COND                   PIC X.
           05 SO-QTY                    PIC 9(9).
       01  TRANSIT-OUTPUT-RECORD.
           05 TO-ID                     PIC X(12).
           05 TO-SOURCE                 PIC X(6).
           05 TO-DEST                   PIC X(6).
           05 TO-PART                   PIC X(10).
           05 TO-COND                   PIC X.
           05 TO-ORIGINAL               PIC 9(9).
           05 TO-OUTSTANDING            PIC 9(9).
