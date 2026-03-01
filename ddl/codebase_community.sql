-- MySQL dump 10.13  Distrib 8.0.42, for Win64 (x86_64)
--
-- Host: localhost    Database: codebase_community
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
-- Table structure for table `badges`
--

DROP TABLE IF EXISTS `badges`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `badges` (
  `Id` int NOT NULL,
  `UserId` int DEFAULT NULL,
  `Name` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `Date` text COLLATE utf8mb4_unicode_ci,
  PRIMARY KEY (`Id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `comments`
--

DROP TABLE IF EXISTS `comments`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `comments` (
  `Id` int NOT NULL,
  `PostId` int DEFAULT NULL,
  `Score` int DEFAULT NULL,
  `Text` text COLLATE utf8mb4_unicode_ci,
  `CreationDate` text COLLATE utf8mb4_unicode_ci,
  `UserId` int DEFAULT NULL,
  `UserDisplayName` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  PRIMARY KEY (`Id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `posthistory`
--

DROP TABLE IF EXISTS `posthistory`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `posthistory` (
  `Id` int NOT NULL,
  `PostHistoryTypeId` int DEFAULT NULL,
  `PostId` int DEFAULT NULL,
  `RevisionGUID` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `CreationDate` text COLLATE utf8mb4_unicode_ci,
  `UserId` int DEFAULT NULL,
  `Text` text COLLATE utf8mb4_unicode_ci,
  `Comment` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `UserDisplayName` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  PRIMARY KEY (`Id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `postlinks`
--

DROP TABLE IF EXISTS `postlinks`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `postlinks` (
  `Id` int NOT NULL,
  `CreationDate` text COLLATE utf8mb4_unicode_ci,
  `PostId` int DEFAULT NULL,
  `RelatedPostId` int DEFAULT NULL,
  `LinkTypeId` int DEFAULT NULL,
  PRIMARY KEY (`Id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `posts`
--

DROP TABLE IF EXISTS `posts`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `posts` (
  `Id` int NOT NULL,
  `PostTypeId` int DEFAULT NULL,
  `AcceptedAnswerId` int DEFAULT NULL,
  `CreaionDate` text COLLATE utf8mb4_unicode_ci,
  `Score` int DEFAULT NULL,
  `ViewCount` int DEFAULT NULL,
  `Body` text COLLATE utf8mb4_unicode_ci,
  `OwnerUserId` int DEFAULT NULL,
  `LasActivityDate` text COLLATE utf8mb4_unicode_ci,
  `Title` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `Tags` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `AnswerCount` int DEFAULT NULL,
  `CommentCount` int DEFAULT NULL,
  `FavoriteCount` int DEFAULT NULL,
  `LastEditorUserId` int DEFAULT NULL,
  `LastEditDate` text COLLATE utf8mb4_unicode_ci,
  `CommunityOwnedDate` text COLLATE utf8mb4_unicode_ci,
  `ParentId` int DEFAULT NULL,
  `ClosedDate` text COLLATE utf8mb4_unicode_ci,
  `OwnerDisplayName` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `LastEditorDisplayName` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  PRIMARY KEY (`Id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `tags`
--

DROP TABLE IF EXISTS `tags`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `tags` (
  `Id` int NOT NULL,
  `TagName` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `Count` int DEFAULT NULL,
  `ExcerptPostId` int DEFAULT NULL,
  `WikiPostId` int DEFAULT NULL,
  PRIMARY KEY (`Id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `users`
--

DROP TABLE IF EXISTS `users`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `users` (
  `Id` int NOT NULL,
  `Reputation` int DEFAULT NULL,
  `CreationDate` text COLLATE utf8mb4_unicode_ci,
  `DisplayName` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `LastAccessDate` text COLLATE utf8mb4_unicode_ci,
  `WebsiteUrl` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `Location` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `AboutMe` text COLLATE utf8mb4_unicode_ci,
  `Views` int DEFAULT NULL,
  `UpVotes` int DEFAULT NULL,
  `DownVotes` int DEFAULT NULL,
  `AccountId` int DEFAULT NULL,
  `Age` int DEFAULT NULL,
  `ProfileImageUrl` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  PRIMARY KEY (`Id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `votes`
--

DROP TABLE IF EXISTS `votes`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `votes` (
  `Id` int NOT NULL,
  `PostId` int DEFAULT NULL,
  `VoteTypeId` int DEFAULT NULL,
  `CreationDate` date DEFAULT NULL,
  `UserId` int DEFAULT NULL,
  `BountyAmount` bigint DEFAULT NULL,
  PRIMARY KEY (`Id`)
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

-- Dump completed on 2025-12-05  5:27:53
