"""
================================================================
 AstraWatch - Moteur de prédiction du risque d'asthme
 RYDI Group © 2024

 Priorité de chargement :
   1. MindSpore (Huawei)  ← moteur principal
   2. scikit-learn         ← fallback automatique
   3. Règles heuristiques  ← fallback d'urgence

 Niveaux de risque :
   1 → Normal     (SpO2 ≥ 95%, HR 60-100, AQI bon)
   2 → Attention  (légère dégradation)
   3 → Danger     (intervention recommandée)
   4 → Urgent     (appel médecin)
   5 → CRISE      (urgence absolue)
================================================================
"""

import os
import numpy as np

# ── Chemins ────────────────────────────────────────────────
_MODEL_DIR    = os.path.join(os.path.dirname(__file__), '..', 'model_output')
_MS_CKPT      = os.path.join(_MODEL_DIR, 'astrawatch_mindspore.ckpt')
_SKL_MODEL    = os.path.join(_MODEL_DIR, 'astrawatch_model.pkl')
_SCALER_PATH  = os.path.join(_MODEL_DIR, 'scaler.pkl')

FEATURES = ['spo2', 'heart_rate', 'aqi', 'co2', 'temperature', 'humidity']

RISK_LABELS = {
    1: "Normal",
    2: "Attention",
    3: "Danger",
    4: "Urgent",
    5: "CRISE",
}

INPUT_DIM   = 6
NUM_CLASSES = 5


# ================================================================
#  DÉFINITION DU RÉSEAU MINDSPORE
# ================================================================

def _build_net():
    """Reconstruit l'architecture AstraNet pour le chargement."""
    import mindspore.nn as nn

    class AstraNet(nn.Cell):
        def __init__(self):
            super(AstraNet, self).__init__()
            self.fc1     = nn.Dense(INPUT_DIM, 64)
            self.fc2     = nn.Dense(64, 32)
            self.fc3     = nn.Dense(32, 16)
            self.fc4     = nn.Dense(16, NUM_CLASSES)
            self.relu    = nn.ReLU()
            self.dropout = nn.Dropout(keep_prob=0.85)
            self.bn1     = nn.BatchNorm1d(64)
            self.bn2     = nn.BatchNorm1d(32)

        def construct(self, x):
            x = self.relu(self.bn1(self.fc1(x)))
            x = self.dropout(x)
            x = self.relu(self.bn2(self.fc2(x)))
            x = self.relu(self.fc3(x))
            x = self.fc4(x)
            return x

    return AstraNet()


# ================================================================
#  PRÉDICTEUR PRINCIPAL
# ================================================================

class AstraPredictor:
    """
    Prédicateur de risque d'asthme.
    Utilise MindSpore en priorité, puis sklearn, puis règles.
    """

    MODE_MINDSPORE  = "MindSpore (Huawei)"
    MODE_SKLEARN    = "scikit-learn (fallback)"
    MODE_HEURISTIC  = "Règles heuristiques (fallback)"

    def __init__(self):
        self._mode   = None
        self._net    = None      # Réseau MindSpore
        self._model  = None      # Modèle sklearn
        self._scaler = None      # Normaliseur commun

        self._load_scaler()
        self._load_mindspore() or self._load_sklearn()

    # ── Chargement scaler ───────────────────────────────────
    def _load_scaler(self):
        try:
            import joblib
            if os.path.exists(_SCALER_PATH):
                self._scaler = joblib.load(_SCALER_PATH)
        except Exception:
            pass

    # ── Chargement MindSpore ────────────────────────────────
    def _load_mindspore(self) -> bool:
        try:
            import mindspore
            mindspore.set_context(mode=mindspore.PYNATIVE_MODE, device_target="CPU")

            if not os.path.exists(_MS_CKPT):
                print(f"[PREDICT] Checkpoint MindSpore non trouvé : {_MS_CKPT}")
                return False

            net        = _build_net()
            param_dict = mindspore.load_checkpoint(_MS_CKPT)
            mindspore.load_param_into_net(net, param_dict)
            net.set_train(False)

            self._net  = net
            self._mode = self.MODE_MINDSPORE
            print(f"[PREDICT] ✅ MindSpore {mindspore.__version__} chargé")
            return True

        except ImportError:
            print("[PREDICT] MindSpore non installé → pip install mindspore==2.3.0")
            return False
        except Exception as e:
            print(f"[PREDICT] MindSpore erreur : {e}")
            return False

    # ── Chargement sklearn ──────────────────────────────────
    def _load_sklearn(self) -> bool:
        try:
            import joblib
            if not os.path.exists(_SKL_MODEL):
                print(f"[PREDICT] Modèle sklearn non trouvé → mode heuristique")
                self._mode = self.MODE_HEURISTIC
                return False

            self._model = joblib.load(_SKL_MODEL)
            self._mode  = self.MODE_SKLEARN
            print(f"[PREDICT] ✅ sklearn chargé (fallback)")
            return True

        except Exception as e:
            print(f"[PREDICT] sklearn erreur : {e} → mode heuristique")
            self._mode = self.MODE_HEURISTIC
            return False

    # ── Prédiction publique ─────────────────────────────────
    def predict(self, data: dict) -> int:
        """Retourne un niveau de risque entre 1 et 5."""
        spo2   = float(data.get('spo2',        98))
        hr     = float(data.get('heart_rate',   72))
        aqi    = float(data.get('aqi',          20))
        co2    = float(data.get('co2',         450))
        temp   = float(data.get('temperature',  22))
        hum    = float(data.get('humidity',     50))

        features = np.array([[spo2, hr, aqi, co2, temp, hum]], dtype=np.float32)

        if self._scaler is not None:
            features = self._scaler.transform(features).astype(np.float32)

        if self._net is not None:
            return self._predict_mindspore(features)
        if self._model is not None:
            return self._predict_sklearn(features)
        return self._predict_rules(spo2, hr, aqi, co2)

    # ── MindSpore inference ─────────────────────────────────
    def _predict_mindspore(self, features: np.ndarray) -> int:
        from mindspore import Tensor
        x      = Tensor(features)
        logits = self._net(x)
        risk   = int(logits.argmax(axis=1).asnumpy()[0]) + 1  # 0-4 → 1-5
        return max(1, min(5, risk))

    # ── sklearn inference ───────────────────────────────────
    def _predict_sklearn(self, features: np.ndarray) -> int:
        risk = int(self._model.predict(features)[0])
        return max(1, min(5, risk))

    # ── Règles heuristiques ─────────────────────────────────
    def _predict_rules(self, spo2, hr, aqi, co2) -> int:
        """Règles cliniques basées sur les seuils médicaux."""
        score = 0

        if   spo2 >= 95: score += 0
        elif spo2 >= 92: score += 2
        elif spo2 >= 90: score += 4
        elif spo2 >= 85: score += 6
        else:            score += 8

        if   60 <= hr <= 100: score += 0
        elif hr <= 110:       score += 1
        elif hr <= 125:       score += 2
        else:                 score += 3

        if   aqi <= 50:  score += 0
        elif aqi <= 100: score += 1
        elif aqi <= 150: score += 2
        else:            score += 3

        if   co2 <= 800:  score += 0
        elif co2 <= 1200: score += 1
        elif co2 <= 1600: score += 2
        else:             score += 3

        if   score <= 1:  return 1
        elif score <= 3:  return 2
        elif score <= 6:  return 3
        elif score <= 10: return 4
        else:             return 5

    # ── Utilitaires ─────────────────────────────────────────
    def get_label(self, risk_level: int) -> str:
        return RISK_LABELS.get(risk_level, "Inconnu")

    @property
    def mode(self) -> str:
        return self._mode or self.MODE_HEURISTIC
