-- MySQL dump 10.13  Distrib 8.0.42, for Win64 (x86_64)
--
-- Host: localhost    Database: toxicology
-- ------------------------------------------------------
-- Server version	8.0.42

/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;
/*!40101 SET @OLD_CHARACTER_SET_RESULTS=@@CHARACTER_SET_RESULTS */;
/*!40101 SET @OLD_COLLATION_CONNECTION=@@COLLATION_CONNECTION */;
/*!50503 SET NAMES utf8 */;
/*!40103 SET @OLD_TIME_ZONE=@@TIME_ZONE */;
/*!40103 SET TIME_ZONE='+00:00' */;
/*!40014 SET @OLD_UNIQUE_CHECKS=@@UNIQUE_CHECKS, UNIQUE_CHECKS=0 */;
/*!40014 SET @OLD_FOREIGN_KEY_CHECKS=@@FOREIGN_KEY_CHECKS, FOREIGN_KEY_CHECKS=0 */;
/*!40101 SET @OLD_SQL_MODE=@@SQL_MODE, SQL_MODE='NO_AUTO_VALUE_ON_ZERO' */;
/*!40111 SET @OLD_SQL_NOTES=@@SQL_NOTES, SQL_NOTES=0 */;

--
-- Table structure for table `atom`
--

DROP TABLE IF EXISTS `atom`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `atom` (
  `atom_id` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `molecule_id` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT 'NULL',
  `element` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT 'NULL',
  PRIMARY KEY (`atom_id`),
  KEY `atom_ibfk_1` (`molecule_id`),
  CONSTRAINT `atom_ibfk_1` FOREIGN KEY (`molecule_id`) REFERENCES `molecule` (`molecule_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `bond`
--

DROP TABLE IF EXISTS `bond`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `bond` (
  `bond_id` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `molecule_id` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT 'NULL',
  `bond_type` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT 'NULL',
  PRIMARY KEY (`bond_id`),
  KEY `bond_ibfk_1` (`molecule_id`),
  CONSTRAINT `bond_ibfk_1` FOREIGN KEY (`molecule_id`) REFERENCES `molecule` (`molecule_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `connected`
--

DROP TABLE IF EXISTS `connected`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `connected` (
  `atom_id` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `atom_id2` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `bond_id` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT 'NULL',
  PRIMARY KEY (`atom_id`,`atom_id2`),
  KEY `connected_ibfk_1` (`bond_id`),
  KEY `connected_ibfk_2` (`atom_id2`),
  CONSTRAINT `connected_ibfk_1` FOREIGN KEY (`bond_id`) REFERENCES `bond` (`bond_id`),
  CONSTRAINT `connected_ibfk_2` FOREIGN KEY (`atom_id2`) REFERENCES `atom` (`atom_id`),
  CONSTRAINT `connected_ibfk_3` FOREIGN KEY (`atom_id`) REFERENCES `atom` (`atom_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `molecule`
--

DROP TABLE IF EXISTS `molecule`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `molecule` (
  `molecule_id` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `label` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT 'NULL',
  PRIMARY KEY (`molecule_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40103 SET TIME_ZONE=@OLD_TIME_ZONE */;

/*!40101 SET SQL_MODE=@OLD_SQL_MODE */;
/*!40014 SET FOREIGN_KEY_CHECKS=@OLD_FOREIGN_KEY_CHECKS */;
/*!40014 SET UNIQUE_CHECKS=@OLD_UNIQUE_CHECKS */;
/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
/*!40101 SET CHARACTER_SET_RESULTS=@OLD_CHARACTER_SET_RESULTS */;
/*!40101 SET COLLATION_CONNECTION=@OLD_COLLATION_CONNECTION */;
/*!40111 SET SQL_NOTES=@OLD_SQL_NOTES */;

-- Dump completed on 2025-12-05  5:31:42
