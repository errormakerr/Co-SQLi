-- MySQL dump 10.13  Distrib 8.0.42, for Win64 (x86_64)
--
-- Host: localhost    Database: superhero
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
-- Table structure for table `alignment`
--

DROP TABLE IF EXISTS `alignment`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `alignment` (
  `id` int NOT NULL,
  `alignment` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT 'NULL',
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `attribute`
--

DROP TABLE IF EXISTS `attribute`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `attribute` (
  `id` int NOT NULL,
  `attribute_name` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT 'NULL',
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `colour`
--

DROP TABLE IF EXISTS `colour`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `colour` (
  `id` int NOT NULL,
  `colour` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT 'NULL',
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `gender`
--

DROP TABLE IF EXISTS `gender`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `gender` (
  `id` int NOT NULL,
  `gender` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT 'NULL',
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `hero_attribute`
--

DROP TABLE IF EXISTS `hero_attribute`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `hero_attribute` (
  `hero_id` int DEFAULT NULL,
  `attribute_id` int DEFAULT NULL,
  `attribute_value` int DEFAULT NULL,
  KEY `hero_attribute_ibfk_1` (`hero_id`),
  KEY `hero_attribute_ibfk_2` (`attribute_id`),
  CONSTRAINT `hero_attribute_ibfk_1` FOREIGN KEY (`hero_id`) REFERENCES `superhero` (`id`),
  CONSTRAINT `hero_attribute_ibfk_2` FOREIGN KEY (`attribute_id`) REFERENCES `attribute` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `hero_power`
--

DROP TABLE IF EXISTS `hero_power`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `hero_power` (
  `hero_id` int DEFAULT NULL,
  `power_id` int DEFAULT NULL,
  KEY `hero_power_ibfk_1` (`power_id`),
  KEY `hero_power_ibfk_2` (`hero_id`),
  CONSTRAINT `hero_power_ibfk_1` FOREIGN KEY (`power_id`) REFERENCES `superpower` (`id`),
  CONSTRAINT `hero_power_ibfk_2` FOREIGN KEY (`hero_id`) REFERENCES `superhero` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `publisher`
--

DROP TABLE IF EXISTS `publisher`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `publisher` (
  `id` int NOT NULL,
  `publisher_name` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT 'NULL',
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `race`
--

DROP TABLE IF EXISTS `race`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `race` (
  `id` int NOT NULL,
  `race` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT 'NULL',
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `superhero`
--

DROP TABLE IF EXISTS `superhero`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `superhero` (
  `id` int NOT NULL,
  `superhero_name` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT 'NULL',
  `full_name` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT 'NULL',
  `gender_id` int DEFAULT NULL,
  `eye_colour_id` int DEFAULT NULL,
  `hair_colour_id` int DEFAULT NULL,
  `skin_colour_id` int DEFAULT NULL,
  `race_id` int DEFAULT NULL,
  `publisher_id` int DEFAULT NULL,
  `alignment_id` int DEFAULT NULL,
  `height_cm` int DEFAULT NULL,
  `weight_kg` int DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `superhero_ibfk_1` (`skin_colour_id`),
  KEY `superhero_ibfk_2` (`race_id`),
  KEY `superhero_ibfk_3` (`publisher_id`),
  KEY `superhero_ibfk_4` (`hair_colour_id`),
  KEY `superhero_ibfk_5` (`gender_id`),
  KEY `superhero_ibfk_6` (`eye_colour_id`),
  KEY `superhero_ibfk_7` (`alignment_id`),
  CONSTRAINT `superhero_ibfk_1` FOREIGN KEY (`skin_colour_id`) REFERENCES `colour` (`id`),
  CONSTRAINT `superhero_ibfk_2` FOREIGN KEY (`race_id`) REFERENCES `race` (`id`),
  CONSTRAINT `superhero_ibfk_3` FOREIGN KEY (`publisher_id`) REFERENCES `publisher` (`id`),
  CONSTRAINT `superhero_ibfk_4` FOREIGN KEY (`hair_colour_id`) REFERENCES `colour` (`id`),
  CONSTRAINT `superhero_ibfk_5` FOREIGN KEY (`gender_id`) REFERENCES `gender` (`id`),
  CONSTRAINT `superhero_ibfk_6` FOREIGN KEY (`eye_colour_id`) REFERENCES `colour` (`id`),
  CONSTRAINT `superhero_ibfk_7` FOREIGN KEY (`alignment_id`) REFERENCES `alignment` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `superpower`
--

DROP TABLE IF EXISTS `superpower`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `superpower` (
  `id` int NOT NULL,
  `power_name` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT 'NULL',
  PRIMARY KEY (`id`)
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

-- Dump completed on 2025-12-05  5:29:45
