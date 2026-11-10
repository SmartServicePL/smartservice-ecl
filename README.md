# Danfoss ECL310 — węzeł cieplny (integracja Smart Service)

Integracja Home Assistant, która czyta regulator węzła cieplnego Danfoss ECL Comfort 296 / 310 przez Modbus/TCP:
temperatury, zadane, nastawy, krzywą grzewczą, tryby, alarmy i licznik ciepła (M-bus).

**Sama z siebie niczego w regulatorze nie zmienia.** Od wersji 0.2.0 ma usługę *Zapisz nastawę*. Usługa zmienia
tylko kilka nastaw obiegu 1, nigdy nie wyżej niż ustawił właściciel, i działa tylko wtedy, gdy ktoś ją wywoła
(zob. „Zapis nastaw”).
Encji do zapisu nie ma, więc w panelu nie ma suwaków. Integracja nie wymaga żadnych dodatkowych bibliotek
(`requirements: []`).

## Obsługiwane regulatory

| Regulator | Klucz aplikacji | Stan |
|---|---|---|
| ECL Comfort 310 / 296 z Ethernetem | A237.1, A237.2 (ogrzewanie + c.w.u. z zasobnikiem) | odczyt v0.1.1, zapis nastaw A237.1 v0.2.0 |
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

*Ustawienia › Urządzenia i usługi › Dodaj integrację › Danfoss ECL310*:

- **Adres IP regulatora**,
- **Port**: 502,
- **Adres Modbus**: 1 (fabrycznie). Działa też 254, czyli adres serwisowy przy jednym regulatorze.

Integracja sprawdza połączenie i klucz aplikacji. Adres IP można później zmienić przez *Zmień konfigurację*, bez usuwania
regulatora (rozpoznaje go po numerze seryjnym).

## Encje

| Encja | Skąd (parametr Danfoss) |
|---|---|
| Temperatura zewnętrzna (S1), Temperatura pokojowa – obieg 1 (S2), Temperatura zasilania – obieg 1 (S3), Temperatura powrotu – obieg 1 (S5), Temperatura górna i dolna – obieg 2 (c.w.u., S6 i S8) | wejścia S, ×0,01 °C (A237.1); nazwy jak w ECL Portal: Outdoor temp., Room temp. (HC1), Flow temp. (HC1), Return temp. (HC1), Upper / Lower temp. (DHW2) |
| Pozostałe wejścia | A237.1: brak (aplikacja ich nie używa); A237.2: S2, S4, S7… domyślnie wyłączone, wejście bez roli podające 0 jest niedostępne |
| Zadana pokojowa (R2), Zadana zasilania (R3), Zadana powrotu (R5) – obieg 1; Zadana górna – obieg 2 (c.w.u., R6) | 11252, 11253, 11255, 12256 |
| Nastawy komfort i oszczędna – obieg 1 (pokój) i obieg 2 (c.w.u.) | 11180–11181, 12190–12191 |
| Krzywa – obieg 1: zasilanie przy −30, −15, −5, 0, 5 i 15 °C | 11400–11405 |
| Tryb i status – obieg 1 oraz obieg 2 (c.w.u.) | 4201–4202, 4211–4212 |
| Ograniczenie powrotu działa, Tryb ręczny – obieg 1, Alarm, Błąd czujnika | 4220, 4201, 1024–1025, 2054–2055 |
| Przekaźniki i triaki | 4006–4011, 4000–4005 (diagnostyczne, domyślnie wyłączone) |
| Licznik ciepła: zasilanie, powrót, moc, energia | 6006–6015, tylko gdy licznik M-bus jest podpięty (typ danych 0) |

- Czujnik niepodłączony (regulator podaje 192 °C) i odczyt poza −50…150 °C dają stan **niedostępny**. Powód jest
  w dzienniku i w diagnostyce.
- Parametr, którego regulator nie ma (wyjątek Modbus 02), też jest niedostępny. Integracja nie pyta o niego w każdym cyklu.
- Odczyt co 30 s (jedno połączenie, regulator zamyka bezczynne po ok. 75 s). Nastawy i krzywa są czytane raz na godzinę.
- **S5 („Temperatura powrotu – obieg 1”, w portalu „Return temp. (HC1)”) to powrót strony pierwotnej** (sieci
  ciepłowniczej, przy zaworze M1), a nie powrót z grzejników. Ograniczenie powrotu regulatora działa na tej temperaturze.
  S3 („Temperatura zasilania – obieg 1”) mierzy zasilanie za wymiennikiem, wspólne dla grzejników i ładowania zasobnika.
- **Role czujników sprawdź z „Przeglądem wejść” na wyświetlaczu regulatora.** Instalacja może być podłączona inaczej.
- Przekaźniki i triaki mają neutralne nazwy (Przekaźnik 1…6, Triak 1…6). Opis komunikacji Danfoss odsyła po ich
  przypisanie do pomp P1–P3 i zaworu M1 do opisu aplikacji, a tego nie dało się potwierdzić z tekstu.

## Zapis nastaw (od 0.2.0)

Usługa `smartservice_ecl.zapisz_parametr` (*Zapisz nastawę*) z polami `pnu` i `wartosc` zapisuje jedną nastawę
funkcją Modbus 0x06. Używa tego samego połączenia co odczyt. Działa tylko z kluczem aplikacji **A237.1** i nie
działa, gdy obieg 1 jest w trybie ręcznym.

| Parametr | PNU | Zakres (jak w regulatorze) |
|---|---|---|
| Zadana pokojowa komfort | 11180 | 5,0–40,0 °C, krok 0,5 K |
| Zadana pokojowa oszczędna | 11181 | 5,0–40,0 °C, krok 0,5 K, nie wyżej niż komfort |
| Krzywa: zasilanie przy −30, −15, −5, 0, 5 i 15 °C | 11400–11405 | 10–150 °C, punkty nie rosną wraz z temperaturą zewnętrzną |
| Maks. zasilania | 11178 | 10–150 °C, jednorazowo |

- **Nigdy wyżej niż wartość właściciela**, czyli ta, którą regulator miał przed pierwszym zapisem integracji.
  Integracja nastawy tylko obniża i przywraca. Regulator trzyma ostatnią zapisaną wartość także wtedy, gdy Home
  Assistant nie działa, więc żaden zapis nie zostawi nastawy wyżej, niż ustawił właściciel.
- Bezpieczną wartość docelową (np. granice dla podłogówki) wybiera program, który wywołuje usługę.
- Każdy inny parametr (m.in. nachylenie 11175, tryby, zegar, c.w.u.) i każda wartość spoza zakresu są odrzucane.
  Do regulatora nie idzie wtedy żadne zapytanie, a powód trafia do dziennika.
- Krzywą obniża się od najcieplejszego punktu (11405), a podnosi od najzimniejszego (11400).
- Każda nastawa może być zapisana najwyżej raz na dobę, a wszystkich zapisów na dobę może być najwyżej 10.
  Regulator przechowuje nastawy w pamięci trwałej, dlatego zapisów jest mało.
- Po 3 s integracja czyta wartość kontrolnie i zwraca wynik: `poprzednio`, `wartosc`, `odczyt`, `zgodny`. Gdy
  odczyt się nie zgadza, tego samego dnia można raz powtórzyć tę samą wartość.
- Przed pierwszym zapisem danej nastawy integracja zapamiętuje wartość z regulatora. Usługa
  `smartservice_ecl.przywroc_parametr` (*Przywróć nastawę*) zapisuje ją z powrotem.
- **Ręczna zmiana wygrywa.** Jeśli nastawę zmieniono na regulatorze po zapisie integracji, przywrócenie niczego nie
  zapisuje. Zostaje wartość ustawiona ręcznie.
- Zapisy, kopie i dziennik są w *Pobierz diagnostykę* (`writes`).
- **Węzeł zwykle należy do dostawcy ciepła.** Zanim użyjesz zapisu, zapytaj go o zgodę.

## MIGIELS

Encje mają stałe klucze (`unique_id` = `<numer seryjny>_<klucz>`), więc MIGIELS podpowiada je sam w kreatorze, na ekranie
„Regulator węzła cieplnego”. Gdy sterowanie ogrzewaniem jest włączone, MIGIELS ustawia nastawy z tabeli „Zapis nastaw”
tą usługą. Przed zmianą robi kopię, a po każdym zapisie czyta wartość kontrolnie. Po wyłączeniu sterowania przywraca
poprzednie nastawy.

## Diagnostyka

*Pobierz diagnostykę* daje surowe rejestry (bez adresu IP i numeru seryjnego) do porównania z wyświetlaczem regulatora.

## Źródła

Danfoss, *ECL Comfort 210 / 296 / 310, communication description*, VI.LG.V5.02 (2017); Danfoss, *Installation Guide
ECL Comfort 210/296/310, A237/A337* (087H3806); Modbus Application Protocol V1.1b3; Modbus Messaging on TCP/IP
Implementation Guide V1.0b. Kod jest napisany od zera. Danfoss i ECL Comfort są znakami towarowymi Danfoss A/S.
Integracja nie jest produktem Danfoss. Nazwa „Danfoss ECL310” opisuje regulator, który integracja czyta; autorem
integracji jest Smart Service.

## Licencja

MIT — zob. `LICENSE`.
