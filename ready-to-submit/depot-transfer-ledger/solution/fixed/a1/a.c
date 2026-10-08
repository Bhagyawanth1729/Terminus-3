SORT-EVENTS.
    IF EVENT-COUNT < 2 EXIT PARAGRAPH END-IF
    PERFORM VARYING WS-I FROM 1 BY 1 UNTIL WS-I >= EVENT-COUNT
        MOVE "N" TO WS-SWAPPED
        PERFORM VARYING WS-J FROM 1 BY 1 UNTIL WS-J > EVENT-COUNT - WS-I
            MOVE "N" TO WS-SORT-NEEDED
            IF E-DATE(WS-J) > E-DATE(WS-J + 1)
                MOVE "Y" TO WS-SORT-NEEDED
            ELSE
                IF E-DATE(WS-J) = E-DATE(WS-J + 1)
                    IF E-SEQ(WS-J) > E-SEQ(WS-J + 1)
                        MOVE "Y" TO WS-SORT-NEEDED
                    ELSE
                        IF E-SEQ(WS-J) = E-SEQ(WS-J + 1)
                            IF E-ID(WS-J) > E-ID(WS-J + 1)
                                MOVE "Y" TO WS-SORT-NEEDED
                            END-IF
                        END-IF
                    END-IF
                END-IF
            END-IF
            IF WS-SORT-NEEDED = "Y"
                MOVE EVENT-ENTRY(WS-J) TO TEMP-EVENT
                MOVE EVENT-ENTRY(WS-J + 1) TO EVENT-ENTRY(WS-J)
                MOVE TEMP-EVENT TO EVENT-ENTRY(WS-J + 1)
                MOVE "Y" TO WS-SWAPPED
            END-IF
        END-PERFORM
        IF WS-SWAPPED = "N" EXIT PERFORM END-IF
    END-PERFORM.
