# Zmiany

## 0.1.0

- Pierwsza wersja: odczyt regulatora Danfoss ECL Comfort 296 / 310 z kluczem A237.1 / A237.2 przez Modbus/TCP —
  temperatury S1–S10, zadane, nastawy, krzywa w sześciu punktach, tryby i statusy, ograniczenie powrotu, tryb ręczny,
  alarm, błąd czujnika, wyjścia i licznik ciepła M-bus.
- Tylko odczyt: własny klient Modbus/TCP z funkcjami 0x04 i 0x03, bez żadnej funkcji zapisu i bez zależności.
- A237.1: role S1, S2 (pokój), S3 (zasilanie za wymiennikiem), S5 (powrót strony pierwotnej), S6 i S8 (zasobnik
  góra i dół); wyjścia z neutralnymi nazwami.
- Czujnik niepodłączony (192 °C) i parametr, którego regulator nie ma, są niedostępne z powodem w diagnostyce.
