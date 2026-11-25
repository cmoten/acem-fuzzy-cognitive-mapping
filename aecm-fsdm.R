library(tidyverse)
library(DiceDesign)
library(jsonlite)
setwd("~/Documents/r_projects/SMA_AECM/SMA-ECMapp/cause-and-consequence-model")
source("fsdm.R")
library(FCMapper)

#Get Filtered Data-----
aecm_data <- readRDS("../data/aecmfull.RDS")

filter_values <- c("TradeForeign",
                   "PeaceOps",
                   "IOCampaigns",
                   "MilAid",
                   "RuleofLaw",
                   "PolStability",
                   "SocialFragment",
                   "DomPolInterfere",
                   "MilSecCoop")


aecm_reduced <- aecm_data %>% dplyr::filter(From %in% filter_values | To %in% filter_values)
new_data <- data.frame(
  From = filter_values,
  To = "AccessandInfluence",
  Valence = c("Pos", "Pos", "Neg", "Pos", "Pos",
              "Pos", "Neg", "Neg", "Pos")
)
aecm_reduced <- aecm_reduced |> bind_rows(new_data)

aecm_reduced$Valence <- ifelse(aecm_reduced$Valence=="Pos","Positive","Negative")
edge_fuzzy_weights <- c("VL","L","M","H","VH")
random_weights <- sample(edge_fuzzy_weights, size = nrow(aecm_reduced), replace = TRUE)
aecm_reduced$ValanceWeight <- random_weights

#Develop Concept Data-----
aecm_concept_names <- unique(c(aecm_reduced$From, aecm_reduced$To))
n <- length(aecm_concept_names)
aecm_concept_list <- list()

aecm_concept_df <- tibble(
  name = "placeholder",
  variable = "placeholder",
  description = "placeholder",
  values =
    tibble(min = 0, max = 0, description = "placeholder"),
  group = "placeholder"
)


for(i in 1:n) {
  tibble_item <- tibble(
    name = aecm_concept_names[i],
    variable = aecm_concept_names[i],
    description = "A description",
    values =
      tibble(
      min = 0,
      max = 1,
      description = "Normalized Value"
    ),
    group = "Outcomes"
  )
  aecm_concept_df <- bind_rows(aecm_concept_df, tibble_item)
  
}

aecm_concept_df <- aecm_concept_df[-1, ]

concept_path <- paste0("models/AECM/concepts.json")
jsonlite::write_json(aecm_concept_df, path = concept_path)

#Develop Relations-----

aecm_relation_df <- tibble(
  name = "placeholder",
  affects = list(tibble())
)

for(i in 1:n){
  concept <- aecm_concept_names[i]
  relation_df <- aecm_reduced |> dplyr::filter(From %in% concept)
  num_rows <- nrow(relation_df)
  if(num_rows == 0){
    tmp_tibble <- tibble(
      name = c(concept),
      affects = list(tibble())
    )
  } else {
    tmp_tibble <- tibble(
      name = concept,
      affects = list(
      tibble(variable = relation_df$To, 
             direction = relation_df$Valence, 
             weight = relation_df$ValanceWeight)
      )
    )
  }
    aecm_relation_df <- bind_rows(aecm_relation_df, tmp_tibble)
}

aecm_relation_df <- aecm_relation_df[-1, ]
relations_path <- paste0("models/AECM/relations.json")
jsonlite::write_json(aecm_relation_df, path = relations_path)

#Create Fuzzy Model-----
M <- createFuzzyModel("models/AECM")

#Create Fuzzy Scenarios-----
start_values <- runif(n, min = 0.01, max = 0.99)
start_change <- NA
scenario_df <- tibble(
  name = aecm_concept_names,
  startvalue = start_values,
  startchange = start_change,
  description = "A description"
)
peace_ops_row <- which(scenario_df$name=='PeaceOps')
new_peace_value <- scenario_df$startvalue[peace_ops_row] * 1.1
if(new_peace_value > 1){
  scenario_df$startchange[peace_ops_row] <- 0.99
} else {
  scenario_df$startchange[peace_ops_row] <- new_peace_value
}


peace_scenario_path <- paste0("models/AECM/scenarios/IncreasePeace/scenario.json")
jsonlite::write_json(scenario_df, path = peace_scenario_path)

scenario_path <- "models/AECM/scenarios/IncreasePeace"

S <- createFuzzyScenario(scenario_path, M)


#Run Model-----
#aecm_test_model <- solveModel(S$StartValues, S$ChangeTo, 10, M, "Linear")

aecm_matrix <- M$Relates
aecm_matrix[is.na(aecm_matrix)] <- 0
colnames(aecm_matrix) <- NULL
rownames(aecm_matrix) <- NULL
FCMapper::check.matrix(aecm_matrix)
aecm_base <- FCMapper::nochanges.scenario(aecm_matrix,
                                          concept.names = M$Cn,
                                          iter = 25)


aecm_base |> 
  dplyr::arrange(desc(Equilibrium_value))

aecm_increase_peace <- FCMapper::changes.scenario(aecm_matrix,
                                                  concept.names = M$Cn,
                                                  iter = 25,
                                                  set.concepts = "PeaceOps",
                                                  set.values = 1)
aecm_compare <- FCMapper::comp.scenarios(aecm_base, aecm_increase_peace) |> 
  mutate(pos = ifelse(Percent_change > 0, TRUE, FALSE))

aecm_compare |> 
  filter(abs(Percent_change) > 1) |> 
  ggplot(aes(x=factor(Concept), y = Percent_change)) +
  geom_bar(stat = "identity", aes(fill = pos), show.legend = FALSE) +
  geom_text(aes(label = paste(round(Percent_change, 2), "%"),
                vjust = ifelse(Percent_change >= 0, 0, 1))) +
  scale_y_continuous("Pecent Change", labels = scales::label_percent()) +
  ggtitle("Comparison of Base Scenario and High Law Enforcement") +
  xlab("") +
  coord_flip() +
  theme_bw()
