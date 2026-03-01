-- MySQL dump 10.13  Distrib 8.0.42, for Win64 (x86_64)
--
-- Host: localhost    Database: formula_1
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
-- Table structure for table `circuits`
--

DROP TABLE IF EXISTS `circuits`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `circuits` (
  `circuitId` int NOT NULL,
  `circuitRef` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '''',
  `name` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '''',
  `location` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `country` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `lat` double DEFAULT NULL,
  `lng` double DEFAULT NULL,
  `alt` bigint DEFAULT NULL,
  `url` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '''',
  PRIMARY KEY (`circuitId`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `constructorresults`
--

DROP TABLE IF EXISTS `constructorresults`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `constructorresults` (
  `constructorResultsId` int NOT NULL,
  `raceId` int NOT NULL DEFAULT '0',
  `constructorId` int NOT NULL DEFAULT '0',
  `points` double DEFAULT NULL,
  `status` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  PRIMARY KEY (`constructorResultsId`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `constructors`
--

DROP TABLE IF EXISTS `constructors`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `constructors` (
  `constructorId` int NOT NULL,
  `constructorRef` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '''',
  `name` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '''',
  `nationality` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `url` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '''',
  PRIMARY KEY (`constructorId`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `constructorstandings`
--

DROP TABLE IF EXISTS `constructorstandings`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `constructorstandings` (
  `constructorStandingsId` int NOT NULL,
  `raceId` int NOT NULL DEFAULT '0',
  `constructorId` int NOT NULL DEFAULT '0',
  `points` double NOT NULL DEFAULT '0',
  `position` int DEFAULT NULL,
  `positionText` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `wins` int NOT NULL DEFAULT '0',
  PRIMARY KEY (`constructorStandingsId`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `drivers`
--

DROP TABLE IF EXISTS `drivers`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `drivers` (
  `driverId` int NOT NULL,
  `driverRef` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '''',
  `number` int DEFAULT NULL,
  `code` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `forename` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '''',
  `surname` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '''',
  `dob` date DEFAULT NULL,
  `nationality` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `url` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '''',
  PRIMARY KEY (`driverId`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `driverstandings`
--

DROP TABLE IF EXISTS `driverstandings`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `driverstandings` (
  `driverStandingsId` int NOT NULL,
  `raceId` int NOT NULL DEFAULT '0',
  `driverId` int NOT NULL DEFAULT '0',
  `points` double NOT NULL DEFAULT '0',
  `position` int DEFAULT NULL,
  `positionText` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `wins` int NOT NULL DEFAULT '0',
  PRIMARY KEY (`driverStandingsId`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `laptimes`
--

DROP TABLE IF EXISTS `laptimes`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `laptimes` (
  `raceId` int NOT NULL,
  `driverId` int NOT NULL,
  `lap` int NOT NULL,
  `position` int DEFAULT NULL,
  `time` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `milliseconds` int DEFAULT NULL,
  PRIMARY KEY (`raceId`,`driverId`,`lap`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `pitstops`
--

DROP TABLE IF EXISTS `pitstops`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `pitstops` (
  `raceId` int NOT NULL,
  `driverId` int NOT NULL,
  `stop` int NOT NULL,
  `lap` int NOT NULL,
  `time` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `duration` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `milliseconds` int DEFAULT NULL,
  PRIMARY KEY (`raceId`,`driverId`,`stop`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `qualifying`
--

DROP TABLE IF EXISTS `qualifying`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `qualifying` (
  `qualifyId` int NOT NULL,
  `raceId` int NOT NULL DEFAULT '0',
  `driverId` int NOT NULL DEFAULT '0',
  `constructorId` int NOT NULL DEFAULT '0',
  `number` int NOT NULL DEFAULT '0',
  `position` int DEFAULT NULL,
  `q1` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `q2` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `q3` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  PRIMARY KEY (`qualifyId`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `races`
--

DROP TABLE IF EXISTS `races`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `races` (
  `raceId` int NOT NULL,
  `year` int NOT NULL DEFAULT '0',
  `round` int NOT NULL DEFAULT '0',
  `circuitId` int NOT NULL DEFAULT '0',
  `name` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '''',
  `date` date NOT NULL,
  `time` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `url` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  PRIMARY KEY (`raceId`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `results`
--

DROP TABLE IF EXISTS `results`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `results` (
  `resultId` int NOT NULL,
  `raceId` int NOT NULL DEFAULT '0',
  `driverId` int NOT NULL DEFAULT '0',
  `constructorId` int NOT NULL DEFAULT '0',
  `number` int DEFAULT NULL,
  `grid` int NOT NULL DEFAULT '0',
  `position` int DEFAULT NULL,
  `positionText` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '''',
  `positionOrder` int NOT NULL DEFAULT '0',
  `points` double NOT NULL DEFAULT '0',
  `laps` int NOT NULL DEFAULT '0',
  `time` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `milliseconds` int DEFAULT NULL,
  `fastestLap` int DEFAULT NULL,
  `rank` int DEFAULT '0',
  `fastestLapTime` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `fastestLapSpeed` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `statusId` int NOT NULL DEFAULT '0',
  PRIMARY KEY (`resultId`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `seasons`
--

DROP TABLE IF EXISTS `seasons`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `seasons` (
  `year` int NOT NULL DEFAULT '0',
  `url` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '''',
  PRIMARY KEY (`year`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `status`
--

DROP TABLE IF EXISTS `status`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `status` (
  `statusId` int NOT NULL,
  `status` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '''',
  PRIMARY KEY (`statusId`)
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

-- Dump completed on 2025-12-05  5:29:08
