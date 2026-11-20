## **Détection d'anomalies sur le réseau électrique**

---

**Cursus concerné** : MLOps

**Difficulté** : 07/10

---

### **Description détaillée**

L'objectif de ce projet est de développer un **service de surveillance du réseau électrique français**, capable de signaler un comportement anormal de la consommation ou de la production, et maintenu par un pipeline automatisé de bout en bout.

RTE publie en accès libre les données éCO2mix : consommation réalisée, prévisions de consommation établies la veille et réactualisées le jour même, production détaillée par filière, échanges aux frontières et estimation des émissions de carbone, au pas de quart d'heure. Le jeu national est rafraîchi tous les quarts d'heure et le jeu régional une fois par heure, avec le détail par région et le solde des échanges entre régions limitrophes. L'historique remonte à 2012, avec des données consolidées et définitives disponibles de 2013 à aujourd'hui.

Une anomalie peut être un pic ou un creux de consommation inexpliqué, une production s'écartant fortement de son régime habituel, un écart anormal entre la prévision et le réalisé, ou une défaillance de la chaîne de mesure elle-même.

L'accent du projet est mis sur **la chaîne de production, pas sur la performance brute du modèle**. Un modèle simple, versionné, monitoré, déployé et réentraînable automatiquement vaut infiniment mieux qu'un modèle sophistiqué resté dans un notebook.

Aucune connaissance préalable du secteur de l'énergie n'est requise : au niveau 1, il s'agit d'une série de nombres indexée par le temps, avec une saisonnalité marquée et une cadence de publication imposée.

**Attention, saisonnalité et anomalie sont ici presque impossibles à distinguer pour un modèle naïf.** La consommation électrique suit un cycle journalier, hebdomadaire et annuel très prononcé. Un dimanche d'août ressemble à une panne majeure vu par un détecteur non désaisonnalisé, et une vague de froid déclenchera une alerte permanente pendant deux semaines.

#### **Pistes à explorer, par difficulté**

**Niveau 1 - Une série, une chaîne complète**

* Détection d'anomalies sur la consommation nationale, avec une chaîne allant de l'ingestion au déploiement effectivement bouclée.
* Baselines documentées dès le départ : écart à la même heure du même jour de la semaine précédente, et écart à la prévision publiée par RTE.
* Désaisonnalisation explicite avant toute détection, et gestion du calendrier (jours fériés, changements d'heure, vacances scolaires).
* Constitution d'un petit jeu d'événements de référence - vagues de froid, épisodes caniculaires, jours fériés, mouvements sociaux - pour disposer d'une évaluation qualitative dès le début.

**Niveau 2 - Passage à l'échelle et flotte de modèles**

* Extension aux douze régions métropolitaines, avec l'arbitrage entre modèle global et flotte, et la gestion du versionnement et de la promotion associée.
* Détection multivariée exploitant conjointement consommation, filières de production et échanges entre régions.
* Historisation propre d'un flux continu : partitionnement, idempotence, gestion des trous de publication et des retards.
* Politique d'alerte élaborée : regroupement, hiérarchisation, suppression des doublons entre régions voisines.

**Niveau 3 - Boucle de rétroaction et observabilité**

* Circuit de qualification humaine des alertes, et exploitation des qualifications comme source d'évaluation dans le temps.
* Distinction entre **régime saisonnier atypique et véritable dégradation du modèle**.
* Confrontation systématique entre les alertes émises sur données temps réel et ce que révèlent les données consolidées publiées un mois plus tard.
* Réentraînement automatisé.
* Monitoring segmenté par région et par filière.

#### **Data**

* éCO2mix national temps réel, pas de quinze minutes : [https://odre.opendatasoft.com/explore/dataset/eco2mix-national-tr/api/](https://odre.opendatasoft.com/explore/dataset/eco2mix-national-tr/api/)
* éCO2mix régional temps réel : [https://odre.opendatasoft.com/explore/dataset/eco2mix-regional-tr/api/](https://odre.opendatasoft.com/explore/dataset/eco2mix-regional-tr/api/)
* éCO2mix national consolidé et définitif, depuis 2012 : [https://odre.opendatasoft.com/explore/dataset/eco2mix-national-cons-def/](https://odre.opendatasoft.com/explore/dataset/eco2mix-national-cons-def/)
* éCO2mix régional consolidé et définitif, depuis 2013 : [https://odre.opendatasoft.com/explore/dataset/eco2mix-regional-cons-def/](https://odre.opendatasoft.com/explore/dataset/eco2mix-regional-cons-def/)
* Portail Open Data Réseaux Énergies : [https://opendata.reseaux-energies.fr/](https://opendata.reseaux-energies.fr/)
* Documentation de l'API Opendatasoft (pagination, filtres, agrégations) : [https://help.opendatasoft.com/apis/ods-explore-v2/](https://help.opendatasoft.com/apis/ods-explore-v2/)
* ENTSO-E Transparency Platform, extension européenne, jeton gratuit : [https://transparency.entsoe.eu/](https://transparency.entsoe.eu/)
* Open-Meteo, historique et prévisions météo, sans clé : [https://open-meteo.com/en/docs](https://open-meteo.com/en/docs)

Note: un quota de 50 000 appels API par utilisateur et par mois s'applique sur ces jeux de données, mis en place en réaction à des téléchargements automatisés à des fréquences disproportionnées par rapport à la cadence de publication.

---

#### **Bibliographie**

* [What is data drift in ML, and how to detect and handle it](https://www.evidentlyai.com/ml-in-production/data-drift) : détection de dérive en pratique
* [Forecasting: Principles and Practice (3rd ed)](https://otexts.com/fpp3/) : Hyndman & Athanasopoulos, *Forecasting: Principles and Practice*, chapitres sur la décomposition saisonnière
* [[1802.04431] Detecting Spacecraft Anomalies Using LSTMs and Nonparametric Dynamic Thresholding](https://arxiv.org/abs/1802.04431) : Hundman et al., détection d'anomalies sur télémétrie avec seuillage non paramétrique
* [https://github.com/facebook/prophet](https://github.com/facebook/prophet) : modélisation de saisonnalités multiples et de jours fériés
* [https://github.com/linkedin/luminol](https://github.com/linkedin/luminol) : bibliothèque légère de détection d'anomalies
* [https://nixtlaverse.nixtla.io/statsforecast/docs/tutorials/anomalydetection.html](https://nixtlaverse.nixtla.io/statsforecast/docs/tutorials/anomalydetection.html) : modèle pertinent pour ce projet
