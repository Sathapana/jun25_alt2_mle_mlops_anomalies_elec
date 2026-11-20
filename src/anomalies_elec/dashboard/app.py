"""Application Streamlit pour la surveillance du réseau électrique éCO2mix."""

from __future__ import annotations

import streamlit as st

from anomalies_elec.config import load_config, load_reference_events
from anomalies_elec.storage.parquet_store import ParquetStore


def main() -> None:
    st.set_page_config(
        page_title="Surveillance Réseau Électrique — éCO2mix MLOps",
        layout="wide",
    )
    cfg = load_config()
    store = ParquetStore(cfg.storage.data_dir)

    st.title("Surveillance d'Anomalies sur le Réseau Électrique Français (éCO2mix)")
    st.caption(
        f"Périmètre par défaut : {cfg.project.default_unique_id} | "
        f"Pas : {cfg.project.freq} | Budget max : {cfg.models.alert_budget_per_week} alertes/semaine"
    )

    tab_live, tab_events, tab_qualify = st.tabs(
        [
            "1. Surveillance & Résidus",
            "2. Événements de Référence",
            "3. Qualification Humaine des Alertes",
        ]
    )

    with tab_live:
        series_df = store.read_series(layer=cfg.storage.processed_subdir, name="national_tr")
        if series_df.empty:
            st.info(
                "Aucune série locale trouvée dans `data/processed/`. "
                "Lancez le pipeline d'ingestion ou appelez `POST /detect`."
            )
        else:
            st.dataframe(series_df.tail(50), use_container_width=True)

    with tab_events:
        st.subheader("Catalogue d'événements historiques de référence")
        events = load_reference_events()
        for ev in events:
            with st.expander(f"{ev['name']} ({ev['start_date']} → {ev['end_date']})"):
                st.write(f"**Catégorie :** `{ev['category']}`")
                st.write(f"**Comportement attendu :** {ev['expected_behavior']}")

    with tab_qualify:
        st.subheader("Qualification des alertes détectées")
        alerts_df = store.read_alerts()
        if alerts_df.empty:
            st.info("Aucune alerte en attente de qualification.")
        else:
            st.dataframe(alerts_df, use_container_width=True)


if __name__ == "__main__":
    main()
