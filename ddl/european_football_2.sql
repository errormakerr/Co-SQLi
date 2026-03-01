-- MySQL dump 10.13  Distrib 8.0.42, for Win64 (x86_64)
--
-- Host: localhost    Database: european_football_2
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
-- Table structure for table `country`
--

DROP TABLE IF EXISTS `country`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `country` (
  `id` int NOT NULL,
  `name` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `league`
--

DROP TABLE IF EXISTS `league`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `league` (
  `id` int NOT NULL,
  `country_id` int DEFAULT NULL,
  `name` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `match`
--

DROP TABLE IF EXISTS `match`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `match` (
  `id` int NOT NULL,
  `country_id` int DEFAULT NULL,
  `league_id` int DEFAULT NULL,
  `season` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `stage` int DEFAULT NULL,
  `date` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `match_api_id` int DEFAULT NULL,
  `home_team_api_id` int DEFAULT NULL,
  `away_team_api_id` int DEFAULT NULL,
  `home_team_goal` int DEFAULT NULL,
  `away_team_goal` int DEFAULT NULL,
  `home_player_X1` int DEFAULT NULL,
  `home_player_X2` int DEFAULT NULL,
  `home_player_X3` int DEFAULT NULL,
  `home_player_X4` int DEFAULT NULL,
  `home_player_X5` int DEFAULT NULL,
  `home_player_X6` int DEFAULT NULL,
  `home_player_X7` int DEFAULT NULL,
  `home_player_X8` int DEFAULT NULL,
  `home_player_X9` int DEFAULT NULL,
  `home_player_X10` int DEFAULT NULL,
  `home_player_X11` int DEFAULT NULL,
  `away_player_X1` int DEFAULT NULL,
  `away_player_X2` int DEFAULT NULL,
  `away_player_X3` int DEFAULT NULL,
  `away_player_X4` int DEFAULT NULL,
  `away_player_X5` int DEFAULT NULL,
  `away_player_X6` int DEFAULT NULL,
  `away_player_X7` int DEFAULT NULL,
  `away_player_X8` int DEFAULT NULL,
  `away_player_X9` int DEFAULT NULL,
  `away_player_X10` int DEFAULT NULL,
  `away_player_X11` int DEFAULT NULL,
  `home_player_Y1` int DEFAULT NULL,
  `home_player_Y2` int DEFAULT NULL,
  `home_player_Y3` int DEFAULT NULL,
  `home_player_Y4` int DEFAULT NULL,
  `home_player_Y5` int DEFAULT NULL,
  `home_player_Y6` int DEFAULT NULL,
  `home_player_Y7` int DEFAULT NULL,
  `home_player_Y8` int DEFAULT NULL,
  `home_player_Y9` int DEFAULT NULL,
  `home_player_Y10` int DEFAULT NULL,
  `home_player_Y11` int DEFAULT NULL,
  `away_player_Y1` int DEFAULT NULL,
  `away_player_Y2` int DEFAULT NULL,
  `away_player_Y3` int DEFAULT NULL,
  `away_player_Y4` int DEFAULT NULL,
  `away_player_Y5` int DEFAULT NULL,
  `away_player_Y6` int DEFAULT NULL,
  `away_player_Y7` int DEFAULT NULL,
  `away_player_Y8` int DEFAULT NULL,
  `away_player_Y9` int DEFAULT NULL,
  `away_player_Y10` int DEFAULT NULL,
  `away_player_Y11` int DEFAULT NULL,
  `home_player_1` int DEFAULT NULL,
  `home_player_2` int DEFAULT NULL,
  `home_player_3` int DEFAULT NULL,
  `home_player_4` int DEFAULT NULL,
  `home_player_5` int DEFAULT NULL,
  `home_player_6` int DEFAULT NULL,
  `home_player_7` int DEFAULT NULL,
  `home_player_8` int DEFAULT NULL,
  `home_player_9` int DEFAULT NULL,
  `home_player_10` int DEFAULT NULL,
  `home_player_11` int DEFAULT NULL,
  `away_player_1` int DEFAULT NULL,
  `away_player_2` int DEFAULT NULL,
  `away_player_3` int DEFAULT NULL,
  `away_player_4` int DEFAULT NULL,
  `away_player_5` int DEFAULT NULL,
  `away_player_6` int DEFAULT NULL,
  `away_player_7` int DEFAULT NULL,
  `away_player_8` int DEFAULT NULL,
  `away_player_9` int DEFAULT NULL,
  `away_player_10` int DEFAULT NULL,
  `away_player_11` int DEFAULT NULL,
  `goal` text COLLATE utf8mb4_unicode_ci,
  `shoton` text COLLATE utf8mb4_unicode_ci,
  `shotoff` text COLLATE utf8mb4_unicode_ci,
  `foulcommit` text COLLATE utf8mb4_unicode_ci,
  `card` text COLLATE utf8mb4_unicode_ci,
  `cross` text COLLATE utf8mb4_unicode_ci,
  `corner` text COLLATE utf8mb4_unicode_ci,
  `possession` text COLLATE utf8mb4_unicode_ci,
  `B365H` double DEFAULT NULL,
  `B365D` double DEFAULT NULL,
  `B365A` double DEFAULT NULL,
  `BWH` double DEFAULT NULL,
  `BWD` double DEFAULT NULL,
  `BWA` double DEFAULT NULL,
  `IWH` double DEFAULT NULL,
  `IWD` double DEFAULT NULL,
  `IWA` double DEFAULT NULL,
  `LBH` double DEFAULT NULL,
  `LBD` double DEFAULT NULL,
  `LBA` double DEFAULT NULL,
  `PSH` double DEFAULT NULL,
  `PSD` double DEFAULT NULL,
  `PSA` double DEFAULT NULL,
  `WHH` double DEFAULT NULL,
  `WHD` double DEFAULT NULL,
  `WHA` double DEFAULT NULL,
  `SJH` double DEFAULT NULL,
  `SJD` double DEFAULT NULL,
  `SJA` double DEFAULT NULL,
  `VCH` double DEFAULT NULL,
  `VCD` double DEFAULT NULL,
  `VCA` double DEFAULT NULL,
  `GBH` double DEFAULT NULL,
  `GBD` double DEFAULT NULL,
  `GBA` double DEFAULT NULL,
  `BSH` double DEFAULT NULL,
  `BSD` double DEFAULT NULL,
  `BSA` double DEFAULT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `player`
--

DROP TABLE IF EXISTS `player`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `player` (
  `id` int NOT NULL,
  `player_api_id` int DEFAULT NULL,
  `player_name` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `player_fifa_api_id` int DEFAULT NULL,
  `birthday` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `height` int DEFAULT NULL,
  `weight` int DEFAULT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `player_attributes`
--

DROP TABLE IF EXISTS `player_attributes`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `player_attributes` (
  `id` int NOT NULL,
  `player_fifa_api_id` int DEFAULT NULL,
  `player_api_id` int DEFAULT NULL,
  `date` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `overall_rating` int DEFAULT NULL,
  `potential` int DEFAULT NULL,
  `preferred_foot` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `attacking_work_rate` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `defensive_work_rate` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `crossing` int DEFAULT NULL,
  `finishing` int DEFAULT NULL,
  `heading_accuracy` int DEFAULT NULL,
  `short_passing` int DEFAULT NULL,
  `volleys` int DEFAULT NULL,
  `dribbling` int DEFAULT NULL,
  `curve` int DEFAULT NULL,
  `free_kick_accuracy` int DEFAULT NULL,
  `long_passing` int DEFAULT NULL,
  `ball_control` int DEFAULT NULL,
  `acceleration` int DEFAULT NULL,
  `sprint_speed` int DEFAULT NULL,
  `agility` int DEFAULT NULL,
  `reactions` int DEFAULT NULL,
  `balance` int DEFAULT NULL,
  `shot_power` int DEFAULT NULL,
  `jumping` int DEFAULT NULL,
  `stamina` int DEFAULT NULL,
  `strength` int DEFAULT NULL,
  `long_shots` int DEFAULT NULL,
  `aggression` int DEFAULT NULL,
  `interceptions` int DEFAULT NULL,
  `positioning` int DEFAULT NULL,
  `vision` int DEFAULT NULL,
  `penalties` int DEFAULT NULL,
  `marking` int DEFAULT NULL,
  `standing_tackle` int DEFAULT NULL,
  `sliding_tackle` int DEFAULT NULL,
  `gk_diving` int DEFAULT NULL,
  `gk_handling` int DEFAULT NULL,
  `gk_kicking` int DEFAULT NULL,
  `gk_positioning` int DEFAULT NULL,
  `gk_reflexes` int DEFAULT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `team`
--

DROP TABLE IF EXISTS `team`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `team` (
  `id` int NOT NULL,
  `team_api_id` int DEFAULT NULL,
  `team_fifa_api_id` int DEFAULT NULL,
  `team_long_name` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `team_short_name` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `team_attributes`
--

DROP TABLE IF EXISTS `team_attributes`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `team_attributes` (
  `id` int NOT NULL,
  `team_fifa_api_id` int DEFAULT NULL,
  `team_api_id` int DEFAULT NULL,
  `date` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `buildUpPlaySpeed` int DEFAULT NULL,
  `buildUpPlaySpeedClass` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `buildUpPlayDribbling` int DEFAULT NULL,
  `buildUpPlayDribblingClass` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `buildUpPlayPassing` int DEFAULT NULL,
  `buildUpPlayPassingClass` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `buildUpPlayPositioningClass` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `chanceCreationPassing` int DEFAULT NULL,
  `chanceCreationPassingClass` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `chanceCreationCrossing` int DEFAULT NULL,
  `chanceCreationCrossingClass` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `chanceCreationShooting` int DEFAULT NULL,
  `chanceCreationShootingClass` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `chanceCreationPositioningClass` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `defencePressure` int DEFAULT NULL,
  `defencePressureClass` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `defenceAggression` int DEFAULT NULL,
  `defenceAggressionClass` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `defenceTeamWidth` int DEFAULT NULL,
  `defenceTeamWidthClass` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `defenceDefenderLineClass` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
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

-- Dump completed on 2025-12-05  5:28:37
