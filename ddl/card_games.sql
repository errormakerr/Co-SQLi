-- MySQL dump 10.13  Distrib 8.0.42, for Win64 (x86_64)
--
-- Host: localhost    Database: card_games
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
-- Table structure for table `cards`
--

DROP TABLE IF EXISTS `cards`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `cards` (
  `id` int NOT NULL,
  `artist` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `asciiName` text COLLATE utf8mb4_unicode_ci,
  `availability` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `borderColor` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `cardKingdomFoilId` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `cardKingdomId` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `colorIdentity` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `colorIndicator` text COLLATE utf8mb4_unicode_ci,
  `colors` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `convertedManaCost` double DEFAULT NULL,
  `duelDeck` text COLLATE utf8mb4_unicode_ci,
  `edhrecRank` int DEFAULT NULL,
  `faceConvertedManaCost` double DEFAULT NULL,
  `faceName` text COLLATE utf8mb4_unicode_ci,
  `flavorName` text COLLATE utf8mb4_unicode_ci,
  `flavorText` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `frameEffects` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `frameVersion` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `hand` text COLLATE utf8mb4_unicode_ci,
  `hasAlternativeDeckLimit` int NOT NULL DEFAULT '0',
  `hasContentWarning` int NOT NULL DEFAULT '0',
  `hasFoil` int NOT NULL DEFAULT '0',
  `hasNonFoil` int NOT NULL DEFAULT '0',
  `isAlternative` int NOT NULL DEFAULT '0',
  `isFullArt` int NOT NULL DEFAULT '0',
  `isOnlineOnly` int NOT NULL DEFAULT '0',
  `isOversized` int NOT NULL DEFAULT '0',
  `isPromo` int NOT NULL DEFAULT '0',
  `isReprint` int NOT NULL DEFAULT '0',
  `isReserved` int NOT NULL DEFAULT '0',
  `isStarter` int NOT NULL DEFAULT '0',
  `isStorySpotlight` int NOT NULL DEFAULT '0',
  `isTextless` int NOT NULL DEFAULT '0',
  `isTimeshifted` int NOT NULL DEFAULT '0',
  `keywords` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `layout` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `leadershipSkills` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `life` text COLLATE utf8mb4_unicode_ci,
  `loyalty` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `manaCost` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `mcmId` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `mcmMetaId` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `mtgArenaId` text COLLATE utf8mb4_unicode_ci,
  `mtgjsonV4Id` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `mtgoFoilId` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `mtgoId` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `multiverseId` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `name` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `number` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `originalReleaseDate` text COLLATE utf8mb4_unicode_ci,
  `originalText` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `originalType` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `otherFaceIds` text COLLATE utf8mb4_unicode_ci,
  `power` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `printings` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `promoTypes` text COLLATE utf8mb4_unicode_ci,
  `purchaseUrls` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `rarity` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `scryfallId` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `scryfallIllustrationId` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `scryfallOracleId` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `setCode` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `side` text COLLATE utf8mb4_unicode_ci,
  `subtypes` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `supertypes` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `tcgplayerProductId` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `text` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `toughness` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `type` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `types` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `uuid` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `variations` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `watermark` text COLLATE utf8mb4_unicode_ci,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `foreign_data`
--

DROP TABLE IF EXISTS `foreign_data`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `foreign_data` (
  `id` int NOT NULL,
  `flavorText` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `language` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `multiverseid` int DEFAULT NULL,
  `name` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `text` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `type` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `uuid` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `legalities`
--

DROP TABLE IF EXISTS `legalities`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `legalities` (
  `id` int NOT NULL,
  `format` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `status` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `uuid` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `rulings`
--

DROP TABLE IF EXISTS `rulings`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `rulings` (
  `id` int NOT NULL,
  `date` date DEFAULT NULL,
  `text` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `uuid` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `set_translations`
--

DROP TABLE IF EXISTS `set_translations`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `set_translations` (
  `id` int NOT NULL,
  `language` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `setCode` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `translation` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `sets`
--

DROP TABLE IF EXISTS `sets`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `sets` (
  `id` int NOT NULL,
  `baseSetSize` int DEFAULT NULL,
  `block` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `booster` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `code` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `isFoilOnly` int NOT NULL DEFAULT '0',
  `isForeignOnly` int NOT NULL DEFAULT '0',
  `isNonFoilOnly` int NOT NULL DEFAULT '0',
  `isOnlineOnly` int NOT NULL DEFAULT '0',
  `isPartialPreview` int NOT NULL DEFAULT '0',
  `keyruneCode` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `mcmId` int DEFAULT NULL,
  `mcmIdExtras` int DEFAULT NULL,
  `mcmName` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `mtgoCode` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `name` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `parentCode` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `releaseDate` date DEFAULT NULL,
  `tcgplayerGroupId` int DEFAULT NULL,
  `totalSetSize` int DEFAULT NULL,
  `type` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
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

-- Dump completed on 2025-12-05  5:19:38
