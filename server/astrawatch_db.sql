-- ================================================================
--  AstraWatch — Base de Données MySQL/MariaDB
--  RYDI Group © 2024
--
--  Instructions d'installation :
--    sudo apt install mariadb-server -y
--    sudo mysql_secure_installation
--    sudo mysql -u root -p < astrawatch_db.sql
--
--  Pour lier à Flask (app.py) :
--    pip install flask-sqlalchemy pymysql --break-system-packages
-- ================================================================

-- Créer la base de données
CREATE DATABASE IF NOT EXISTS astrawatch
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE astrawatch;

-- ================================================================
--  TABLE : users
--  Stocke les comptes créés depuis le dashboard web
-- ================================================================
CREATE TABLE IF NOT EXISTS users (
  id          INT AUTO_INCREMENT PRIMARY KEY,
  nom         VARCHAR(100) NOT NULL,
  prenom      VARCHAR(100) NOT NULL,
  email       VARCHAR(255) NOT NULL UNIQUE,
  password_hash VARCHAR(255) NOT NULL,      -- bcrypt hash, jamais plain text
  role        ENUM('patient', 'medecin') NOT NULL DEFAULT 'patient',
  patname     VARCHAR(200) DEFAULT NULL,    -- Nom du patient suivi (médecins)
  created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
  last_login  DATETIME DEFAULT NULL,
  is_active   BOOLEAN DEFAULT TRUE
) ENGINE=InnoDB;

-- ================================================================
--  TABLE : patients
--  Profil médical du patient (lié à un user)
-- ================================================================
CREATE TABLE IF NOT EXISTS patients (
  id              INT AUTO_INCREMENT PRIMARY KEY,
  user_id         INT NOT NULL,
  date_naissance  DATE DEFAULT NULL,
  sexe            ENUM('M','F','Autre') DEFAULT NULL,
  telephone       VARCHAR(20) DEFAULT NULL,
  adresse         VARCHAR(255) DEFAULT NULL,
  medecin_id      INT DEFAULT NULL,          -- FK vers users (médecin référent)
  notes_medicales TEXT DEFAULT NULL,
  created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
  FOREIGN KEY (medecin_id) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB;

-- ================================================================
--  TABLE : sensor_data
--  Toutes les lectures fusionnées ESP32 + Raspberry Pi
-- ================================================================
CREATE TABLE IF NOT EXISTS sensor_data (
  id              BIGINT AUTO_INCREMENT PRIMARY KEY,
  patient_id      INT DEFAULT NULL,           -- NULL si pas encore associé
  -- Vitaux (ESP32 / MAX30102)
  spo2            FLOAT DEFAULT NULL,         -- %
  heart_rate      FLOAT DEFAULT NULL,         -- bpm
  finger_detected BOOLEAN DEFAULT TRUE,
  sim_mode        BOOLEAN DEFAULT FALSE,
  -- Environnement (Raspberry Pi / ENS160 + DHT)
  temperature     FLOAT DEFAULT NULL,         -- °C
  humidity        FLOAT DEFAULT NULL,         -- %
  aqi             FLOAT DEFAULT NULL,         -- Air Quality Index
  co2             FLOAT DEFAULT NULL,         -- ppm eCO2
  tvoc            FLOAT DEFAULT NULL,         -- ppb TVOC
  -- GPS (NEO-6M)
  latitude        DOUBLE DEFAULT NULL,
  longitude       DOUBLE DEFAULT NULL,
  altitude        FLOAT DEFAULT NULL,         -- m
  speed_kmh       FLOAT DEFAULT NULL,         -- km/h
  gps_fix         BOOLEAN DEFAULT FALSE,
  satellites      INT DEFAULT 0,
  -- Prédiction IA MindSpore
  risk_level      TINYINT DEFAULT 0,          -- 0-5
  risk_label      VARCHAR(50) DEFAULT NULL,
  predictive_on   BOOLEAN DEFAULT FALSE,
  -- Meta
  watch_online    BOOLEAN DEFAULT FALSE,
  recorded_at     DATETIME DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_patient  (patient_id),
  INDEX idx_recorded (recorded_at),
  INDEX idx_risk     (risk_level),
  FOREIGN KEY (patient_id) REFERENCES patients(id) ON DELETE SET NULL
) ENGINE=InnoDB;

-- ================================================================
--  TABLE : alerts
--  Journal de toutes les alertes générées
-- ================================================================
CREATE TABLE IF NOT EXISTS alerts (
  id           BIGINT AUTO_INCREMENT PRIMARY KEY,
  patient_id   INT DEFAULT NULL,
  sensor_id    BIGINT DEFAULT NULL,           -- Lecture qui a déclenché l'alerte
  alert_type   ENUM('risk','sos','stable') NOT NULL,
  risk_level   TINYINT DEFAULT NULL,
  message      TEXT DEFAULT NULL,
  sms_sent     BOOLEAN DEFAULT FALSE,
  sms_numbers  VARCHAR(500) DEFAULT NULL,     -- Numéros contactés
  latitude     DOUBLE DEFAULT NULL,
  longitude    DOUBLE DEFAULT NULL,
  gps_fix      BOOLEAN DEFAULT FALSE,
  created_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_patient_alert (patient_id),
  INDEX idx_created       (created_at),
  INDEX idx_type          (alert_type),
  FOREIGN KEY (patient_id) REFERENCES patients(id) ON DELETE SET NULL,
  FOREIGN KEY (sensor_id)  REFERENCES sensor_data(id) ON DELETE SET NULL
) ENGINE=InnoDB;

-- ================================================================
--  TABLE : sms_log
--  Log de chaque SMS envoyé via Nexah
-- ================================================================
CREATE TABLE IF NOT EXISTS sms_log (
  id           BIGINT AUTO_INCREMENT PRIMARY KEY,
  alert_id     BIGINT DEFAULT NULL,
  number       VARCHAR(20) NOT NULL,
  message      TEXT NOT NULL,
  success      BOOLEAN DEFAULT FALSE,
  nexah_code   INT DEFAULT NULL,              -- responsecode Nexah
  nexah_desc   VARCHAR(255) DEFAULT NULL,     -- responsedescription Nexah
  sent_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (alert_id) REFERENCES alerts(id) ON DELETE SET NULL
) ENGINE=InnoDB;

-- ================================================================
--  TABLE : sessions
--  Sessions actives du dashboard web
-- ================================================================
CREATE TABLE IF NOT EXISTS sessions (
  id           VARCHAR(64) PRIMARY KEY,       -- UUID session
  user_id      INT NOT NULL,
  ip_address   VARCHAR(45) DEFAULT NULL,
  user_agent   VARCHAR(500) DEFAULT NULL,
  created_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
  expires_at   DATETIME NOT NULL,
  FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- ================================================================
--  UTILISATEUR MySQL pour l'application Flask
--  (plus sécurisé que d'utiliser root)
-- ================================================================
CREATE USER IF NOT EXISTS 'astrawatch_app'@'localhost'
  IDENTIFIED BY 'AstraWatch2024!';

GRANT SELECT, INSERT, UPDATE, DELETE
  ON astrawatch.*
  TO 'astrawatch_app'@'localhost';

FLUSH PRIVILEGES;

-- ================================================================
--  DONNÉES DE TEST (optionnel — supprimer en production)
-- ================================================================

-- Médecin de test (mot de passe = "test1234" → hash bcrypt)
INSERT IGNORE INTO users (nom, prenom, email, password_hash, role, patname)
VALUES ('Dupont', 'Marie', 'medecin@test.cm',
        '$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TiGTGlIKGcZJiDuGIFHoJ.hGw9H2',
        'medecin', 'Jean Patient');

-- Patient de test
INSERT IGNORE INTO users (nom, prenom, email, password_hash, role)
VALUES ('Patient', 'Jean', 'patient@test.cm',
        '$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TiGTGlIKGcZJiDuGIFHoJ.hGw9H2',
        'patient');

-- ================================================================
--  VUES UTILES
-- ================================================================

-- Vue : dernière lecture par patient
CREATE OR REPLACE VIEW v_latest_reading AS
SELECT
  sd.*,
  u.nom, u.prenom, u.email,
  u.role
FROM sensor_data sd
JOIN patients p    ON sd.patient_id = p.id
JOIN users u       ON p.user_id     = u.id
WHERE sd.id = (
  SELECT MAX(id) FROM sensor_data WHERE patient_id = sd.patient_id
);

-- Vue : statistiques journalières
CREATE OR REPLACE VIEW v_daily_stats AS
SELECT
  patient_id,
  DATE(recorded_at)      AS jour,
  ROUND(AVG(spo2), 2)    AS avg_spo2,
  ROUND(AVG(heart_rate),1) AS avg_hr,
  ROUND(AVG(aqi),1)      AS avg_aqi,
  ROUND(AVG(co2),0)      AS avg_co2,
  MAX(risk_level)        AS max_risk,
  COUNT(*)               AS nb_lectures,
  SUM(CASE WHEN risk_level >= 3 THEN 1 ELSE 0 END) AS nb_alertes
FROM sensor_data
WHERE patient_id IS NOT NULL
GROUP BY patient_id, DATE(recorded_at);

-- ================================================================
--  VÉRIFICATION FINALE
-- ================================================================
SHOW TABLES;
