-- MySQL dump 10.13  Distrib 8.0.42, for Win64 (x86_64)
--
-- Host: localhost    Database: thrombosis_prediction
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
-- Table structure for table `examination`
--

DROP TABLE IF EXISTS `examination`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `examination` (
  `ID` int DEFAULT NULL,
  `Examination Date` date DEFAULT NULL,
  `aCL IgG` double DEFAULT NULL,
  `aCL IgM` double DEFAULT NULL,
  `ANA` int DEFAULT NULL,
  `ANA Pattern` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `aCL IgA` int DEFAULT NULL,
  `Diagnosis` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `KCT` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `RVVT` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `LAC` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `Symptoms` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `Thrombosis` int DEFAULT NULL,
  KEY `examination_ibfk_1` (`ID`),
  CONSTRAINT `examination_ibfk_1` FOREIGN KEY (`ID`) REFERENCES `patient` (`ID`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `laboratory`
--

DROP TABLE IF EXISTS `laboratory`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `laboratory` (
  `ID` int NOT NULL DEFAULT '0',
  `Date` date NOT NULL,
  `GOT` int DEFAULT NULL,
  `GPT` int DEFAULT NULL,
  `LDH` int DEFAULT NULL,
  `ALP` int DEFAULT NULL,
  `TP` double DEFAULT NULL,
  `ALB` double DEFAULT NULL,
  `UA` double DEFAULT NULL,
  `UN` int DEFAULT NULL,
  `CRE` double DEFAULT NULL,
  `T-BIL` double DEFAULT NULL,
  `T-CHO` int DEFAULT NULL,
  `TG` int DEFAULT NULL,
  `CPK` int DEFAULT NULL,
  `GLU` int DEFAULT NULL,
  `WBC` double DEFAULT NULL,
  `RBC` double DEFAULT NULL,
  `HGB` double DEFAULT NULL,
  `HCT` double DEFAULT NULL,
  `PLT` int DEFAULT NULL,
  `PT` double DEFAULT NULL,
  `APTT` bigint DEFAULT NULL,
  `FG` double DEFAULT NULL,
  `PIC` bigint DEFAULT NULL,
  `TAT` bigint DEFAULT NULL,
  `TAT2` bigint DEFAULT NULL,
  `U-PRO` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `IGG` int DEFAULT NULL,
  `IGA` int DEFAULT NULL,
  `IGM` int DEFAULT NULL,
  `CRP` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `RA` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `RF` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `C3` int DEFAULT NULL,
  `C4` int DEFAULT NULL,
  `RNP` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `SM` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `SC170` text COLLATE utf8mb4_unicode_ci,
  `SSA` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `SSB` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `CENTROMEA` text COLLATE utf8mb4_unicode_ci,
  `DNA` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `DNA-II` bigint DEFAULT NULL,
  PRIMARY KEY (`ID`,`Date`),
  CONSTRAINT `laboratory_ibfk_1` FOREIGN KEY (`ID`) REFERENCES `patient` (`ID`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `patient`
--

DROP TABLE IF EXISTS `patient`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `patient` (
  `ID` int NOT NULL DEFAULT '0',
  `SEX` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `Birthday` date DEFAULT NULL,
  `Description` date DEFAULT NULL,
  `First Date` date DEFAULT NULL,
  `Admission` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `Diagnosis` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  PRIMARY KEY (`ID`)
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

-- Dump completed on 2025-12-05  5:31:27
