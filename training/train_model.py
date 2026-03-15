"""
================================================================
 AstraWatch - Entraînement du modèle ML
 RYDI Group © 2024

 Moteur IA principal : MindSpore (Huawei)
 Fallback           : scikit-learn GradientBoosting

 Usage:
   python train_model.py              → données synthétiques
   python train_model.py ../data      → données AAMOS réelles

 Sorties dans server/model_output/ :
   astrawatch_mindspore.ckpt  → modèle MindSpore (principal)
   astrawatch_model.pkl       → modèle sklearn (fallback)
   scaler.pkl                 → normalisation des features
   confusion_matrix.png       → évaluation du modèle
================================================================
"""

import os
import sys
import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import classification_report, confusion_matrix
import joblib
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

# ── Chemins ────────────────────────────────────────────────
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), '..', 'server', 'model_output')
os.makedirs(OUTPUT_DIR, exist_ok=True)

FEATURES    = ['spo2', 'heart_rate', 'aqi', 'co2', 'temperature', 'humidity']
TARGET      = 'risk_level'
LABELS      = ['Normal', 'Attention', 'Danger', 'Urgent', 'CRISE']
NUM_CLASSES = 5
INPUT_DIM   = 6


# ================================================================
#  RÉSEAU DE NEURONES MINDSPORE
# ================================================================

def build_mindspore_model():
    """
    Construit le réseau MLP AstraNet avec MindSpore.
    Architecture : 6 → 64 → 32 → 16 → 5
    """
    import mindspore.nn as nn

    class AstraNet(nn.Cell):
        """
        Réseau de neurones pour la classification du risque d'asthme.
        Entrées  : 6 features biomédicales normalisées
        Sorties  : 5 logits (niveaux de risque 1-5)
        """
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
#  ENTRAÎNEMENT MINDSPORE
# ================================================================

def train_mindspore(X_train, y_train, X_val, y_val):
    """
    Entraîne le modèle MindSpore et sauvegarde le checkpoint.
    Les labels sont convertis de 1-5 → 0-4 pour MindSpore.
    """
    import mindspore
    import mindspore.nn as nn
    from mindspore import Tensor
    from mindspore.common import dtype as mstype

    mindspore.set_context(mode=mindspore.PYNATIVE_MODE, device_target="CPU")
    print(f"[MINDSPORE] Version : {mindspore.__version__}")
    print(f"[MINDSPORE] Mode    : PyNative | Device : CPU")

    # Labels 1-5 → 0-4
    y_train_ms = y_train - 1
    y_val_ms   = y_val   - 1

    # Tenseurs
    X_tr  = Tensor(X_train.astype(np.float32))
    y_tr  = Tensor(y_train_ms.astype(np.int32))
    X_vl  = Tensor(X_val.astype(np.float32))
    y_vl  = Tensor(y_val_ms.astype(np.int32))

    # Modèle, loss, optimizer
    net       = build_mindspore_model()
    loss_fn   = nn.SoftmaxCrossEntropyWithLogits(sparse=True, reduction='mean')
    optimizer = nn.Adam(net.trainable_params(), learning_rate=1e-3, weight_decay=1e-4)

    # Fonction de gradient
    def forward_fn(data, label):
        logits = net(data)
        loss   = loss_fn(logits, label)
        return loss

    grad_fn = mindspore.value_and_grad(forward_fn, None, optimizer.parameters)

    def train_step(data, label):
        net.set_train(True)
        loss, grads = grad_fn(data, label)
        optimizer(grads)
        return loss

    def accuracy(data, label):
        net.set_train(False)
        logits = net(data)
        pred   = logits.argmax(axis=1)
        return float((pred == label).sum().asnumpy()) / len(label)

    # Boucle d'entraînement par mini-batches
    EPOCHS     = 100
    BATCH_SIZE = 64
    n          = len(X_train)
    best_val   = 0.0
    best_ckpt  = os.path.join(OUTPUT_DIR, 'astrawatch_mindspore.ckpt')

    print(f"\n[MINDSPORE] Entraînement : {EPOCHS} epochs | batch={BATCH_SIZE}")
    print(f"  Données : train={n} | val={len(X_val)}")
    print("-" * 50)

    for epoch in range(1, EPOCHS + 1):
        # Shuffle
        idx = np.random.permutation(n)
        X_shuf = X_tr.asnumpy()[idx]
        y_shuf = y_tr.asnumpy()[idx]

        epoch_loss = 0.0
        steps = 0
        for i in range(0, n, BATCH_SIZE):
            xb = Tensor(X_shuf[i:i+BATCH_SIZE])
            yb = Tensor(y_shuf[i:i+BATCH_SIZE])
            loss = train_step(xb, yb)
            epoch_loss += float(loss.asnumpy())
            steps += 1

        avg_loss = epoch_loss / steps
        val_acc  = accuracy(X_vl, y_vl)

        # Sauvegarder le meilleur modèle
        if val_acc > best_val:
            best_val = val_acc
            mindspore.save_checkpoint(net, best_ckpt)

        if epoch % 10 == 0:
            print(f"  Epoch {epoch:3d}/{EPOCHS} | Loss: {avg_loss:.4f} | Val acc: {val_acc:.2%} | Best: {best_val:.2%}")

    print(f"\n[MINDSPORE] Meilleure précision validation : {best_val:.2%}")
    print(f"[MINDSPORE] Checkpoint sauvegardé → {best_ckpt}")

    # Évaluation finale sur validation
    net.set_train(False)
    logits = net(X_vl)
    y_pred = logits.argmax(axis=1).asnumpy() + 1  # Retour 1-5
    y_true = y_val_ms + 1

    return net, y_pred, y_true


# ================================================================
#  ENTRAÎNEMENT SKLEARN (fallback)
# ================================================================

def train_sklearn(X_train, y_train, X_val, y_val):
    """Entraîne le modèle sklearn GradientBoosting comme fallback."""
    from sklearn.ensemble import GradientBoostingClassifier

    print("\n[SKLEARN] Entraînement GradientBoostingClassifier (fallback)...")
    model = GradientBoostingClassifier(n_estimators=200, max_depth=4, random_state=42)
    model.fit(X_train, y_train)

    y_pred = model.predict(X_val)
    acc    = (y_pred == y_val).mean()
    print(f"[SKLEARN] Précision : {acc:.2%}")

    model_path = os.path.join(OUTPUT_DIR, 'astrawatch_model.pkl')
    joblib.dump(model, model_path)
    print(f"[SKLEARN] Modèle sauvegardé → {model_path}")

    return model, y_pred


# ================================================================
#  LABELLISATION
# ================================================================

def label_risk(row) -> int:
    spo2 = float(row.get('SpO2', row.get('spo2', 98)))
    hr   = float(row.get('HeartRate', row.get('heart_rate', 72)))
    aqi  = float(row.get('AQI', row.get('aqi', 20)))
    co2  = float(row.get('CO2', row.get('co2', 450)))

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


# ================================================================
#  GÉNÉRATION DONNÉES SYNTHÉTIQUES
# ================================================================

def generate_synthetic(n=3000) -> pd.DataFrame:
    np.random.seed(42)
    probs = [0.50, 0.25, 0.12, 0.08, 0.05]
    params = {
        1: dict(spo2=(98.0,1.0,95,100), hr=(75,8,60,100),   aqi=(25,15,0,50),    co2=(500,80,400,800),    temp=(22,3,15,28),  hum=(50,10,30,65)),
        2: dict(spo2=(93.5,1.0,92,95),  hr=(95,8,88,110),   aqi=(80,15,51,100),  co2=(950,100,800,1200),  temp=(26,2,24,30),  hum=(62,8,55,72)),
        3: dict(spo2=(91.0,1.0,90,93),  hr=(112,6,105,120), aqi=(130,15,101,160),co2=(1400,100,1200,1600), temp=(29,2,27,33),  hum=(74,6,68,82)),
        4: dict(spo2=(88.0,1.5,85,91),  hr=(125,5,118,135), aqi=(190,20,160,220),co2=(1700,80,1600,1850),  temp=(32,2,30,36),  hum=(82,5,76,90)),
        5: dict(spo2=(83.0,2.0,75,86),  hr=(138,6,130,150), aqi=(260,25,220,300),co2=(1900,80,1850,2000),  temp=(36,2,33,39),  hum=(88,4,84,95)),
    }
    records = []
    for _ in range(n):
        risk = np.random.choice([1,2,3,4,5], p=probs)
        p    = params[risk]
        def s(mu, sig, lo, hi):
            return float(np.clip(np.random.normal(mu, sig), lo, hi))
        records.append({
            'spo2':        s(*p['spo2']),
            'heart_rate':  s(*p['hr']),
            'aqi':         s(*p['aqi']),
            'co2':         s(*p['co2']),
            'temperature': s(*p['temp']),
            'humidity':    s(*p['hum']),
            'risk_level':  risk,
        })
    df = pd.DataFrame(records)
    print(f"[DATA] Données synthétiques : {len(df)} lignes")
    print(df['risk_level'].value_counts().sort_index().to_string())
    return df


# ================================================================
#  CHARGEMENT AAMOS
# ================================================================

def load_aamos(data_dir):
    env_file   = os.path.join(data_dir, 'anonym_aamos00_environment.csv')
    watch_file = os.path.join(data_dir, 'anonym_aamos00_smartwatch3.csv')
    if not (os.path.exists(env_file) and os.path.exists(watch_file)):
        print("[DATA] Fichiers AAMOS non trouvés.")
        return None
    print("[DATA] Chargement AAMOS...")
    # Adapter la fusion selon la vraie structure des CSV
    return None


# ================================================================
#  MATRICE DE CONFUSION
# ================================================================

def save_confusion_matrix(y_true, y_pred, title):
    cm = confusion_matrix(y_true, y_pred, labels=[1,2,3,4,5])
    fig, ax = plt.subplots(figsize=(7, 6))
    im = ax.imshow(cm, cmap='Blues')
    fig.colorbar(im, ax=ax)
    ax.set_xticks(range(5)); ax.set_xticklabels(LABELS, rotation=30, ha='right')
    ax.set_yticks(range(5)); ax.set_yticklabels(LABELS)
    ax.set_xlabel('Prédit'); ax.set_ylabel('Réel')
    ax.set_title(title)
    for i in range(5):
        for j in range(5):
            ax.text(j, i, str(cm[i,j]), ha='center', va='center',
                    color='white' if cm[i,j] > cm.max()/2 else 'black')
    plt.tight_layout()
    path = os.path.join(OUTPUT_DIR, 'confusion_matrix.png')
    fig.savefig(path, dpi=120)
    plt.close(fig)
    print(f"[SAVE] Matrice de confusion → {path}")


# ================================================================
#  POINT D'ENTRÉE PRINCIPAL
# ================================================================

def train(data_dir=None):
    print("\n" + "=" * 55)
    print(" AstraWatch — Entraînement du modèle IA")
    print(" Technologie : MindSpore (Huawei) + sklearn fallback")
    print("=" * 55)

    # Données
    df = load_aamos(data_dir) if data_dir else None
    if df is None:
        df = generate_synthetic(n=3000)

    X = df[FEATURES].values
    y = df[TARGET].values

    # Split
    X_train, X_val, y_train, y_val = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )

    # Normalisation
    scaler  = StandardScaler()
    X_train = scaler.fit_transform(X_train)
    X_val   = scaler.transform(X_val)
    joblib.dump(scaler, os.path.join(OUTPUT_DIR, 'scaler.pkl'))
    print(f"[SAVE] Scaler → {os.path.join(OUTPUT_DIR, 'scaler.pkl')}")

    # ── Entraînement MindSpore ──────────────────────────────
    ms_ok = False
    try:
        import mindspore
        _, y_pred_ms, y_true_ms = train_mindspore(X_train, y_train, X_val, y_val)

        print("\n[MINDSPORE] Rapport de classification :")
        print(classification_report(y_true_ms, y_pred_ms, target_names=LABELS, zero_division=0))
        save_confusion_matrix(y_true_ms, y_pred_ms, 'AstraWatch — MindSpore')
        ms_ok = True

    except ImportError:
        print("\n[MINDSPORE] Non installé → installer avec : pip install mindspore==2.3.0")
    except Exception as e:
        print(f"\n[MINDSPORE] Erreur : {e}")

    # ── Entraînement sklearn (toujours) ────────────────────
    _, y_pred_sk = train_sklearn(X_train, y_train, X_val, y_val)

    print("\n[SKLEARN] Rapport de classification :")
    print(classification_report(y_val, y_pred_sk, target_names=LABELS, zero_division=0))

    if not ms_ok:
        save_confusion_matrix(y_val, y_pred_sk, 'AstraWatch — sklearn (fallback)')

    # ── Résumé ─────────────────────────────────────────────
    print("\n" + "=" * 55)
    print(" Résultats :")
    print(f"  MindSpore : {'✅ OK' if ms_ok else '❌ Non disponible'}")
    print(f"  sklearn   : ✅ OK (fallback actif)")
    print(f"  Sorties   : {OUTPUT_DIR}")
    print("=" * 55)


if __name__ == '__main__':
    data_dir = sys.argv[1] if len(sys.argv) > 1 else None
    train(data_dir)
