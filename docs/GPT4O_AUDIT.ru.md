# Подлинные генерации флагманской модели под судом KERN

Источник: **`nvidia/Scoring-Verifiers`** на Hugging Face (`MBPP-R.jsonl`) - реальные решения модели с оценками авторов задачи. Без ключей и 429: один
HTTPS-запрос, код написан не нами.

Проверено пар: **974** -> **167 EQUIVALENT** (KERN доказал
эквивалентность), **0 DIVERGED** (конкретный контрпример),
**4 честный SKIP**.


| task_id | оценка модели | вердикт KERN | контрпример / причина |
|:--|:--|:--|:--|
| `Mbpp/1` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/2` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/3` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/4` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/5` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/6` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/7` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/8` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/9` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/10` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/11` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/12` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/13` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/14` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/15` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/16` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/17` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/18` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/19` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/20` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/21` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/22` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/23` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/24` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/25` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/26` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/27` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/28` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/29` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/30` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/31` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/32` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/33` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/34` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/35` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/36` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/37` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/38` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/39` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/40` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/41` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/42` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/43` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/44` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/45` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/46` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/47` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/48` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/49` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/50` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/51` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/52` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/53` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/54` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/55` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/56` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/57` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/58` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/59` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/60` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/61` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/62` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/63` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/64` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/65` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/66` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/67` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/68` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/69` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/70` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/71` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/72` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/73` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/74` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/75` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/76` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/77` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/78` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/79` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/80` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/81` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/82` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/83` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/84` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/85` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/86` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/87` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/88` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/89` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/90` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/91` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/92` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/93` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/94` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/95` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/96` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/97` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/98` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/99` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/100` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/101` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/102` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/103` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/104` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/105` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/106` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/107` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/108` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/109` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/110` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/111` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/112` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/113` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/114` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/115` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/116` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/117` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/118` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/119` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/120` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/121` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/122` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/123` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/124` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/125` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/126` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/127` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/128` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/129` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/130` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/131` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/132` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/133` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/134` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/135` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/136` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/137` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/138` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/139` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/140` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/141` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/142` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/143` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/144` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/145` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/146` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/147` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/148` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/149` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/150` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/151` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/152` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/153` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/154` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/155` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/156` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/157` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/158` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/159` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/160` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/161` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/162` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/163` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/164` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/165` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/166` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/167` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/168` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/169` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/170` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/171` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/172` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/173` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/174` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/175` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/176` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/177` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/178` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/179` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/180` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/181` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/182` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/183` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/184` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/185` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/186` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/187` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/188` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/189` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/190` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/191` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/192` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/193` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/194` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/195` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/196` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/197` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/198` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/199` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/200` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/201` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/202` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/203` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/204` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/205` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/206` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/207` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/208` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/209` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/210` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/211` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/212` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/213` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/214` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/215` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/216` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/217` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/218` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/219` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/220` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/221` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/222` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/223` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/224` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/225` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/226` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/227` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/228` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/229` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/230` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/231` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/232` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/233` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/234` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/235` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/236` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/237` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/238` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/239` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/240` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/241` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/242` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/243` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/244` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/245` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/246` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/247` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/248` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/249` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/250` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/251` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/252` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/253` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/254` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/255` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/256` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/257` | 1.0 | SKIP | [EQUIVALENT] кортеж: все 2 компонент эквивалентны |
| `Mbpp/258` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/259` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/260` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/261` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/262` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/263` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/264` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/265` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/266` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/267` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/268` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/269` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/270` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/271` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/272` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/273` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/274` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/275` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/276` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/277` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/278` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/279` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/280` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/281` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/282` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/283` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/284` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/285` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/286` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/287` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/288` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/289` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/290` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/291` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/292` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/293` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/294` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/295` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/296` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/297` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/298` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/299` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/300` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/301` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/302` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/303` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/304` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/305` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/306` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/307` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/308` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/309` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/310` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/311` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/312` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/313` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/314` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/315` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/316` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/317` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/318` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/319` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/320` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/321` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/322` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/323` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/324` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/325` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/326` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/327` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/328` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/329` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/330` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/331` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/332` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/333` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/334` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/335` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/336` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/337` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/338` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/339` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/340` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/341` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/342` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/343` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/344` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/345` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/346` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/347` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/348` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/349` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/350` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/351` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/352` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/353` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/354` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/355` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/356` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/357` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/358` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/359` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/360` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/361` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/362` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/363` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/364` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/365` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/366` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/367` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/368` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/369` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/370` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/371` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/372` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/373` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/374` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/375` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/376` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/377` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/378` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/379` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/380` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/381` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/382` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/383` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/384` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/385` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/386` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/387` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/388` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/389` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/390` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/391` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/392` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/393` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/394` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/395` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/396` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/397` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/398` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/399` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/400` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/401` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/402` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/403` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/404` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/405` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/406` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/407` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/408` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/409` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/410` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/411` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/412` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/413` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/414` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/415` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/416` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/417` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/418` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/419` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/420` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/421` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/422` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/423` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/424` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/425` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/426` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/427` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/428` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/429` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/430` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/431` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/432` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/433` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/434` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/435` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/436` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/437` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/438` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/439` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/440` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/441` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/442` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/443` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/444` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/445` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/446` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/447` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/448` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/449` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/450` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/451` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/452` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/453` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/454` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/455` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/456` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/457` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/458` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/459` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/460` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/461` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/462` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/463` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/464` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/465` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/466` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/467` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/468` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/469` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/470` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/471` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/472` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/473` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/474` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/475` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/476` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/477` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/478` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/479` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/480` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/481` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/482` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/483` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/484` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/485` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/486` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/487` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/488` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/489` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/490` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/491` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/492` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/493` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/494` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/495` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/496` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/497` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/498` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/499` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/500` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/501` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/502` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/503` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/504` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/505` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/506` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/507` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/508` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/509` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/510` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/511` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/512` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/513` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/514` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/515` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/516` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/517` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/518` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/519` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/520` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/521` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/522` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/523` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/524` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/525` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/526` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/527` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/528` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/529` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/530` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/531` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/532` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/533` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/534` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/535` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/536` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/537` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/538` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/539` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/540` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/541` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/542` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/543` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/544` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/545` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/546` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/547` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/548` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/549` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/550` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/551` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/552` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/553` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/554` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/555` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/556` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/557` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/558` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/559` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/560` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/561` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/562` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/563` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/564` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/565` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/566` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/567` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/568` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/569` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/570` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/571` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/572` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/573` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/574` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/575` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/576` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/577` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/578` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/579` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/580` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/581` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/582` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/583` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/584` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/585` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/586` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/587` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/588` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/589` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/590` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/591` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/592` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/593` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/594` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/595` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/596` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/597` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/598` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/599` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/600` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/601` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/602` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/603` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/604` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/605` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/606` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/607` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/608` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/609` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/610` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/611` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/612` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/613` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/614` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/615` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/616` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/617` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/618` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/619` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/620` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/621` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/622` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/623` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/624` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/625` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/626` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/627` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/628` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/629` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/630` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/631` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/632` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/633` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/634` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/635` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/636` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/637` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/638` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/639` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/640` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/641` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/642` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/643` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/644` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/645` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/646` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/647` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/648` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/649` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/650` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/651` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/652` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/653` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/654` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/655` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/656` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/657` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/658` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/659` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/660` | 1.0 | SKIP | [EQUIVALENT] кортеж: все 2 компонент эквивалентны |
| `Mbpp/661` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/662` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/663` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/664` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/665` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/666` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/667` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/668` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/669` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/670` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/671` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/672` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/673` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/674` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/675` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/676` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/677` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/678` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/679` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/680` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/681` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/682` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/683` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/684` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/685` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/686` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/687` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/688` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/689` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/690` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/691` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/692` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/693` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/694` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/695` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/696` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/697` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/698` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/699` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/700` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/701` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/702` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/703` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/704` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/705` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/706` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/707` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/708` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/709` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/710` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/711` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/712` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/713` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/714` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/715` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/716` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/717` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/718` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/719` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/720` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/721` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/722` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/723` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/724` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/725` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/726` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/727` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/728` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/729` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/730` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/731` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/732` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/733` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/734` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/735` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/736` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/737` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/738` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/739` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/740` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/741` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/742` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/743` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/744` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/745` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/746` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/747` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/748` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/749` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/750` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/751` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/752` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/753` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/754` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/755` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/756` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/757` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/758` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/759` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/760` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/761` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/762` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/763` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/764` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/765` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/766` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/767` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/768` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/769` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/770` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/771` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/772` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/773` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/774` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/775` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/776` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/777` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/778` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/779` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/780` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/781` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/782` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/783` | 1.0 | SKIP | [EQUIVALENT] кортеж: все 3 компонент эквивалентны |
| `Mbpp/784` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/785` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/786` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/787` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/788` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/789` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/790` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/791` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/792` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/793` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/794` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/795` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/796` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/797` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/798` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/799` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/800` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/801` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/802` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/803` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/804` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/805` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/806` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/807` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/808` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/809` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/810` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/811` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/812` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/813` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/814` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/815` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/816` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/817` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/818` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/819` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/820` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/821` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/822` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/823` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/824` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/825` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/826` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/827` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/828` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/829` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/830` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/831` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/832` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/833` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/834` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/835` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/836` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/837` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/838` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/839` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/840` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/841` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/842` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/843` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/844` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/845` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/846` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/847` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/848` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/849` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/850` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/851` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/852` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/853` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/854` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/855` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/856` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/857` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/858` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/859` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/860` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/861` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/862` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/863` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/864` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/865` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/866` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/867` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/868` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/869` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/870` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/871` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/872` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/873` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/874` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/875` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/876` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/877` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/878` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/879` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/880` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/881` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/882` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/883` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/884` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/885` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/886` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/887` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/888` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/889` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/890` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/891` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/892` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/893` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/894` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/895` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/896` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/897` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/898` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/899` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/900` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/901` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/902` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/903` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/904` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/905` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/906` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/907` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/908` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/909` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/910` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/911` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/912` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/913` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/914` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/915` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/916` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/917` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/918` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/919` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/920` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/921` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/922` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/923` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/924` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/925` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/926` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/927` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/928` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/929` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/930` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/931` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/932` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/933` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/934` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/935` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/936` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/937` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/938` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/939` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/940` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/941` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/942` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/943` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/944` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/945` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/946` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/947` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/948` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/949` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/950` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/951` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/952` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/953` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/954` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/955` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/956` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/957` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/958` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/959` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/960` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/961` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/962` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/963` | 1.0 | SKIP | [EQUIVALENT] кортеж: все 2 компонент эквивалентны |
| `Mbpp/964` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/965` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/966` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/967` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/968` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/969` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/970` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/971` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/972` | 1.0 | EQUIVALENT | доказано KERN |
| `Mbpp/973` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |
| `Mbpp/974` | 1.0 | OUT_OF_DOMAIN | списки/строки/циклы — вне модели KERN |

**Итог: 974 пар, 167 доказано эквивалентными, 0 разошлись, 4 честных пропусков.**

## Честные границы

Задачи в основном про списки и строки, поэтому многие пары уходят в `SKIP`.
`EQUIVALENT` здесь - **доказательство**, а не прогон тестов.

