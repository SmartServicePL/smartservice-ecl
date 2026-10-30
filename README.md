# Smart Service ECL — węzeł cieplny Danfoss

Integracja Home Assistant, która **tylko czyta** regulator węzła cieplnego Danfoss ECL Comfort 296 / 310 przez Modbus/TCP:
temperatury, zadane, nastawy, krzywą grzewczą, tryby, alarmy i licznik ciepła (M-bus).

**Niczego w regulatorze nie zmienia.** Integracja zna tylko funkcje odczytu Modbus (0x04 i 0x03). Kodu zapisu nie ma
w niej wcale. Nie wymaga też żadnych dodatkowych bibliotek (`requirements: []`).

## Obsługiwane regulatory

| Regulator | Klucz aplikacji | Stan |
|---|---|---|
| ECL Comfort 310 / 296 z Ethernetem | A237.1, A237.2 (ogrzewanie + c.w.u. z zasobnikiem) | v0.1 |
| inne klucze | — | dodanie kończy się komunikatem „Klucz aplikacji … nie jest jeszcze obsługiwany” |

Klucz aplikacji integracja czyta z regulatora (rejestry 2060–2063), nie trzeba go wpisywać. Nie ma trybu „czytaj
wszystko” dla nieznanych kluczy.

## Zanim dodasz

1. Regulator musi mieć adres IP w sieci domowej. Ustawia się go na wyświetlaczu: *Ustawienia wspólne regulatora › System › Ethernet*.
   Fabrycznie jest to 192.168.1.100.
2. **Węzeł zwykle należy do dostawcy ciepła.** Bez jego zgody nie zmieniaj w regulatorze niczego, także adresu sieciowego.
3. **ECL może przyjmować tylko jednego klienta Modbus naraz.** Wyłącz inne połączenia Modbus z tym regulatorem (np. sekcję
   `modbus:` w `configuration.yaml` albo inną integrację).
4. Regulator nie ma haseł ani kontroli dostępu. Trzymaj go w sieci domowej, bez przekierowania portu 502 na routerze.

## Dodanie

*Ustawienia › Urządzenia i usługi › Dodaj integrację › Smart Service ECL*:

- **Adres IP regulatora**,
- **Port**: 502,
- **Adres Modbus**: 1 (fabrycznie). Działa też 254, czyli adres serwisowy przy jednym regulatorze.

Integracja sprawdza połączenie i klucz aplikacji. Adres IP można później zmienić przez *Zmień konfigurację*, bez usuwania
regulatora (rozpoznaje go po numerze seryjnym).

## Encje

| Encja | Skąd (parametr Danfoss) |
|---|---|
| Temperatura zewnętrzna (S1), Temperatura pokojowa (S2), Zasilanie obiegu (S3), Powrót strony pierwotnej (S5), Zasobnik c.w.u. góra (S6) i dół (S8) | wejścia S, ×0,01 °C (A237.1) |
| Pozostałe wejścia (A237.1: S4, S7, S9, S10; A237.2: także S2 i S8) | domyślnie wyłączone (rola zależy od instalacji) |
| Zadana zasilania obiegu, Zadana c.w.u. | 11253, 12256 |
| Nastawy pokojowe i c.w.u. (komfort, oszczędna) | 11180–11181, 12190–12191 |
| Krzywa: zasilanie przy −30, −15, −5, 0, 5 i 15 °C | 11400–11405 |
| Tryb i status ogrzewania i c.w.u. | 4201–4202, 4211–4212 |
| Ograniczenie powrotu działa, Tryb ręczny, Alarm, Błąd czujnika | 4220, 4201, 1024–1025, 2054–2055 |
| Przekaźniki i triaki | 4006–4011, 4000–4005 (diagnostyczne, domyślnie wyłączone) |
| Licznik ciepła: zasilanie, powrót, moc, energia | 6006–6015, tylko gdy licznik M-bus jest podpięty (typ danych 0) |

- Czujnik niepodłączony (regulator podaje 192 °C) i odczyt poza −50…150 °C dają stan **niedostępny**. Powód jest
  w dzienniku i w diagnostyce.
- Parametr, którego regulator nie ma (wyjątek Modbus 02), też jest niedostępny. Integracja nie pyta o niego w każdym cyklu.
- Odczyt co 30 s (jedno połączenie, regulator zamyka bezczynne po ok. 75 s). Nastawy i krzywa są czytane raz na godzinę.
- **S5 to powrót strony pierwotnej** (sieci ciepłowniczej, przy zaworze M1), a nie powrót z grzejników. Ograniczenie
  powrotu regulatora działa na tej temperaturze.
- **Role czujników sprawdź z „Przeglądem wejść” na wyświetlaczu regulatora.** Instalacja może być podłączona inaczej.
- Przekaźniki i triaki mają neutralne nazwy (Przekaźnik 1…6, Triak 1…6). Opis komunikacji Danfoss odsyła po ich
  przypisanie do pomp P1–P3 i zaworu M1 do opisu aplikacji, a tego nie dało się potwierdzić z tekstu.

## MIGIELS

Encje mają stałe klucze (`unique_id` = `<numer seryjny>_<klucz>`), więc MIGIELS podpowiada je sam w kreatorze, na ekranie
„Regulator węzła cieplnego”.

## Diagnostyka

*Pobierz diagnostykę* daje surowe rejestry (bez adresu IP i numeru seryjnego) do porównania z wyświetlaczem regulatora.

## Źródła

Danfoss, *ECL Comfort 210 / 296 / 310, communication description*, VI.LG.V5.02 (2017); Danfoss, *Installation Guide
ECL Comfort 210/296/310, A237/A337* (087H3806); Modbus Application Protocol V1.1b3; Modbus Messaging on TCP/IP
Implementation Guide V1.0b. Kod jest napisany od zera. Danfoss i ECL Comfort są znakami towarowymi Danfoss A/S.
Integracja nie jest produktem Danfoss.

## Licencja

MIT — zob. `LICENSE`.
