-- MySQL dump 10.13  Distrib 8.0.42, for Win64 (x86_64)
--
-- Host: localhost    Database: california_schools
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
-- Table structure for table `frpm`
--

DROP TABLE IF EXISTS `frpm`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `frpm` (
  `CDSCode` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `Academic Year` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `County Code` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `District Code` int DEFAULT NULL,
  `School Code` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `County Name` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `District Name` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `School Name` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `District Type` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `School Type` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `Educational Option Type` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `NSLP Provision Status` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `Charter School (Y/N)` int DEFAULT NULL,
  `Charter School Number` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `Charter Funding Type` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `IRC` int DEFAULT NULL,
  `Low Grade` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `High Grade` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `Enrollment (K-12)` double DEFAULT NULL,
  `Free Meal Count (K-12)` double DEFAULT NULL,
  `Percent (%) Eligible Free (K-12)` double DEFAULT NULL,
  `FRPM Count (K-12)` double DEFAULT NULL,
  `Percent (%) Eligible FRPM (K-12)` double DEFAULT NULL,
  `Enrollment (Ages 5-17)` double DEFAULT NULL,
  `Free Meal Count (Ages 5-17)` double DEFAULT NULL,
  `Percent (%) Eligible Free (Ages 5-17)` double DEFAULT NULL,
  `FRPM Count (Ages 5-17)` double DEFAULT NULL,
  `Percent (%) Eligible FRPM (Ages 5-17)` double DEFAULT NULL,
  `2013-14 CALPADS Fall 1 Certification Status` int DEFAULT NULL,
  PRIMARY KEY (`CDSCode`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `satscores`
--

DROP TABLE IF EXISTS `satscores`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `satscores` (
  `cds` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `rtype` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `sname` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `dname` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `cname` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `enroll12` int NOT NULL,
  `NumTstTakr` int NOT NULL,
  `AvgScrRead` int DEFAULT NULL,
  `AvgScrMath` int DEFAULT NULL,
  `AvgScrWrite` int DEFAULT NULL,
  `NumGE1500` int DEFAULT NULL,
  PRIMARY KEY (`cds`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `schools`
--

DROP TABLE IF EXISTS `schools`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `schools` (
  `CDSCode` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `NCESDist` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `NCESSchool` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `StatusType` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `County` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `District` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `School` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `Street` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `StreetAbr` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `City` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `Zip` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `State` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `MailStreet` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `MailStrAbr` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `MailCity` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `MailZip` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `MailState` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `Phone` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `Ext` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `Website` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `OpenDate` date DEFAULT NULL,
  `ClosedDate` date DEFAULT NULL,
  `Charter` int DEFAULT NULL,
  `CharterNum` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `FundingType` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `DOC` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `DOCType` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `SOC` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `SOCType` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `EdOpsCode` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `EdOpsName` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `EILCode` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `EILName` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `GSoffered` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `GSserved` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `Virtual` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `Magnet` int DEFAULT NULL,
  `Latitude` double DEFAULT NULL,
  `Longitude` double DEFAULT NULL,
  `AdmFName1` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `AdmLName1` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `AdmEmail1` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `AdmFName2` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `AdmLName2` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `AdmEmail2` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `AdmFName3` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `AdmLName3` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `AdmEmail3` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `LastUpdate` date NOT NULL,
  PRIMARY KEY (`CDSCode`)
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

-- Dump completed on 2025-12-05  5:16:26
