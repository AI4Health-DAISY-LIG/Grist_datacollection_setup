# Grist table setup

Ce projet crée automatiquement les colonnes d'une table Grist à partir d'un
fichier YAML. Il peut servir de base à n'importe quel projet de collecte.

## Installation

```powershell
uv sync
Copy-Item .env.example .env
```

Renseignez ensuite `GRIST_API_KEY` et `DOC_ID` dans `.env`. Ne commitez jamais
`.env`.

## Utilisation

Pour tester un schéma sans modifier Grist :

```powershell
uv run python main.py --dry-run
```

Pour créer ou configurer la table :

```powershell
uv run python main.py --table Table1
```

Si `Table1` n'existe pas encore dans le document, le script la crée puis ajoute
les colonnes du fichier YAML. Si elle existe déjà, seules les colonnes absentes
sont ajoutées. La commande peut donc être relancée sans recréer la table ni
dupliquer les colonnes. Les colonnes sont envoyées individuellement pour rester
compatible avec certaines protections réseau d'instances Grist.

Options utiles :

- `--schema chemin` utilise un autre schéma YAML ; par défaut, le script lit
	`data/schema.yml`.
- `--doc ID` remplace `DOC_ID`.
- `--env-file chemin/.env` utilise un autre fichier de configuration.
- `--base URL` vise une autre instance Grist.
- `--keep-defaults` conserve les colonnes `A`, `B` et `C` créées par Grist.

## Format YAML

Chaque élément de `columns` contient un `id` et `fields.label`/`fields.type`.
Ajoutez `description`, `choices`, `formula`, `is_formula`, `widget_options`,
`recalc_when` ou `recalc_deps` selon les besoins.

### Exemple complet

Cet exemple couvre toutes les options interprétées par le chargeur :

```yaml
columns:
	# Colonne simple : les champs Grist sont regroupés sous `fields`.
	- id: nom
		fields:
			label: Nom complet
			type: Text
			description: Nom de la personne collectée.

	# `choices` génère automatiquement les widgetOptions Grist d'une Choice.
	- id: statut
		fields:
			label: Statut
			type: Choice
			description: Etat courant de l'enregistrement.
		choices:
			- nouveau
			- en_cours
			- termine
		choice_options:
			nouveau:
				fillColor: '#DDEBFF'
			en_cours:
				fillColor: '#FFF1C7'
			termine:
				fillColor: '#DDF5E5'

	# `widget_options` est utile pour configurer un widget non-Choice.
	- id: confirme
		fields:
			label: Confirme
			type: Bool
		widget_options:
			widget: Switch

	# Une formule Grist classique est envoyée avec isFormula=true par défaut.
	- id: nom_normalise
		fields:
			label: Nom normalisé
			type: Text
		formula: |
			return ($nom or '').strip().lower()

	# `is_formula: false` crée une formule de déclenchement appliquée aux
	# nouvelles lignes, avec les paramètres de recalcul associés.
	- id: recu_le
		fields:
			label: Reçu le
			type: 'DateTime:Europe/Paris'
		formula: NOW()
		is_formula: false
		recalc_when: 0
		recalc_deps: null

	# `fields` peut aussi contenir directement d'autres propriétés de l'API
	# Grist, par exemple visibleCol ou widgetOptions sous leur nom API.
	- id: commentaire
		fields:
			label: Commentaire
			type: Text
			description: Champ facultatif.
			visibleCol: true
			widgetOptions: '{}'
```

Options disponibles :

- `id` : identifiant technique unique de la colonne.
- `fields.label` : libellé affiché dans Grist, obligatoire.
- `fields.type` : type Grist (`Text`, `Int`, `Bool`, `Choice`, `Any`, etc.),
	obligatoire.
- `fields.description` : description affichée dans Grist, facultative.
- `choices` : liste des choix d'une colonne `Choice`.
- `choice_options` : options associées aux choix ; utilisé avec `choices`.
- `widget_options` : configuration du widget ; convertie en JSON pour Grist.
- `formula` : formule Grist. Elle peut être écrite sur une ligne ou en bloc
	avec `|`.
- `is_formula` : `true` par défaut ; mettre `false` pour une formule de
	déclenchement.
- `recalc_when` et `recalc_deps` : paramètres Grist de recalcul d'une formule.

Les autres propriétés placées dans `fields` sont transmises telles quelles à
l'API Grist. Les noms spécifiques à l'API utilisent leur forme Grist, par
exemple `visibleCol`, `widgetOptions` ou `recalcWhen`.

Le script ne contient aucune donnée métier : noms de colonnes, choix, formules
et options Grist doivent tous être définis dans le YAML. Après la création,
vérifiez les règles d'accès et les formules de déclenchement dans l'interface
Grist.
