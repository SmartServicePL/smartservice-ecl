# Zmiany

## 0.2.1

- Błędy usług *Zapisz nastawę* i *Przywróć nastawę* mają stałe kody (`translation_key`): `pnu_niedozwolony`,
  `poza_zakresem`, `powyzej_wlasciciela`, `limit_doby`, `tryb_reczny`, `brak_polaczenia`, `odczyt_niezgodny`,
  `brak_kopii`, `zmiana_reczna`, `brak_regulatora`. Treść komunikatu bez zmian.
- Pola usług i kształt odpowiedzi bez zmian.

## 0.2.0

- Nowa usługa *Zapisz nastawę* (`smartservice_ecl.zapisz_parametr`) dla A237.1. Zapisuje tylko zadaną pokojową
  komfort (11180) i oszczędną (11181, nie wyżej niż komfort), krzywą obiegu 1 (11400–11405, nierosnącą) oraz
  jednorazowo maks. zasilania (11178), w zakresach regulatora i nigdy wyżej niż wartość sprzed pierwszego zapisu.
  Każdy inny parametr i każda wartość spoza zakresu są odrzucane bez zapytania do regulatora.
- Najwyżej 1 zapis na dobę na nastawę i 10 zapisów na dobę łącznie. Po zapisie odczyt kontrolny, który można raz
  powtórzyć, gdy wartość się nie zgadza.
- Nowa usługa *Przywróć nastawę* (`smartservice_ecl.przywroc_parametr`) przywraca wartość sprzed pierwszego zapisu.
  Ręczna zmiana na regulatorze wygrywa i nie jest nadpisywana.
- Klient Modbus ma jedną funkcję zapisu: 0x06, jeden rejestr. Odpowiedź musi powtórzyć zapytanie.
- Bez encji do zapisu. Odczyt i identyfikatory encji bez zmian.

## 0.1.2

- Integracja i urządzenie nazywają się „Danfoss ECL310”. Model urządzenia z numeru katalogowego regulatora
  (np. „ECL Comfort 296/310” — Danfoss ma jeden numer dla 296 i 310).
- Tytuł wpisu: „ECL 296/310 - A237.1” (bez odczytu modelu „ECL - A237.1”). Wpis z dawnym tytułem „ECL A237.1”
  dostaje nowy tytuł sam; tytuł zmieniony ręcznie zostaje.
- Identyfikatory encji bez zmian — historia, automatyzacje i entity_id zostają.

## 0.1.1

- Nazwy encji jak w ECL Portal Danfoss: obieg 1 (HC1) i obieg 2 (c.w.u.), z numerem wejścia, np. „Temperatura
  zasilania – obieg 1 (S3)” / „Flow temp. (HC1, S3)”. Identyfikatory encji bez zmian, historia i automatyzacje zostają.
- Nowe odczyty: zadana pokojowa (R2) i zadana powrotu (R5) obiegu 1.
- A237.1: bez encji wejść, których aplikacja nie używa (S4, S7, S9, S10); wejście bez roli, które podaje 0, jest
  niedostępne.

## 0.1.0

- Pierwsza wersja: odczyt regulatora Danfoss ECL Comfort 296 / 310 z kluczem A237.1 / A237.2 przez Modbus/TCP —
  temperatury S1–S10, zadane, nastawy, krzywa w sześciu punktach, tryby i statusy, ograniczenie powrotu, tryb ręczny,
  alarm, błąd czujnika, wyjścia i licznik ciepła M-bus.
- Tylko odczyt: własny klient Modbus/TCP z funkcjami 0x04 i 0x03, bez żadnej funkcji zapisu i bez zależności.
- A237.1: role S1, S2 (pokój), S3 (zasilanie za wymiennikiem), S5 (powrót strony pierwotnej), S6 i S8 (zasobnik
  góra i dół); wyjścia z neutralnymi nazwami.
- Czujnik niepodłączony (192 °C) i parametr, którego regulator nie ma, są niedostępne z powodem w diagnostyce.
